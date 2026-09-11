"""笔记列表、搜索、下载。

主站 API 的签名目前纯 Python 算不出来，所以：
- 列表：抓个人主页 HTML 里的 __INITIAL_STATE__（首屏约 30 篇），
        或用 Playwright 打开主页自动滚动、截获 /user_posted 接口拿全部；
- 详情：XhsClient.get_note_by_id_from_html —— 解析笔记页 HTML。
"""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from xhs import XhsClient
from xhs.help import download_file, get_imgs_url_from_note, get_valid_path_name, get_video_url_from_note

from .config import CACHE_FILE, cookie_to_dict

PROFILE_URL = "https://www.xiaohongshu.com/user/profile/{user_id}"
STATE_RE = re.compile(r"window.__INITIAL_STATE__=({.*?})</script>", re.S)


@dataclass
class NoteItem:
    note_id: str
    xsec_token: str
    display_title: str
    type: str  # normal / video

    @property
    def is_video(self) -> bool:
        return self.type == "video"


# ---------------------------------------------------------------- 解析


def _walk_state(obj, found: dict[str, NoteItem]) -> None:
    if isinstance(obj, dict):
        nid = obj.get("noteId") or obj.get("id")
        token = obj.get("xsecToken") or obj.get("xsec_token")
        card = obj.get("noteCard") or obj
        if nid and token and isinstance(card, dict) and ("displayTitle" in card or "type" in card):
            found.setdefault(
                nid,
                NoteItem(nid, token, card.get("displayTitle", ""), card.get("type", "")),
            )
        for v in obj.values():
            _walk_state(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk_state(v, found)


def _notes_from_html(html: str) -> list[NoteItem]:
    m = STATE_RE.search(html)
    if not m:
        return []
    state = json.loads(m.group(1).replace("undefined", "null"))
    found: dict[str, NoteItem] = {}
    _walk_state(state, found)
    return list(found.values())


# ---------------------------------------------------------------- 列表


def fetch_notes_quick(client: XhsClient, user_id: str) -> list[NoteItem]:
    """抓主页 HTML，首屏约 30 篇，不需要浏览器。"""
    res = client.session.get(
        PROFILE_URL.format(user_id=user_id),
        headers={"user-agent": client.user_agent, "referer": "https://www.xiaohongshu.com/"},
        timeout=15,
    )
    notes = _notes_from_html(res.text)
    if not notes:
        raise RuntimeError(f"主页未解析到笔记（HTTP {res.status_code}），可能 cookie 失效或触发验证码")
    return notes


def _fetch_all_in_thread(cookie: str, user_id: str, user_agent: str, headless: bool,
                         progress: Callable[[int], None] | None, max_idle_rounds: int) -> list[NoteItem]:
    from playwright.sync_api import sync_playwright

    found: dict[str, NoteItem] = {}
    state = {"has_more": True}

    def on_response(resp):
        if "/api/sns/web/v1/user_posted" not in resp.url:
            return
        try:
            data = resp.json()
        except Exception:
            return
        d = data.get("data") or {}
        for n in d.get("notes", []):
            found.setdefault(
                n["note_id"],
                NoteItem(n["note_id"], n.get("xsec_token", ""), n.get("display_title", ""), n.get("type", "")),
            )
        if d.get("has_more") is False:
            state["has_more"] = False

    cookies = [
        {"name": k, "value": v, "domain": ".xiaohongshu.com", "path": "/"}
        for k, v in cookie_to_dict(cookie).items()
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(user_agent=user_agent, viewport={"width": 1280, "height": 900})
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.on("response", on_response)
        page.goto(PROFILE_URL.format(user_id=user_id), wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        try:
            init_state = page.evaluate("() => window.__INITIAL_STATE__")
            _walk_state(init_state, found)
        except Exception:
            for n in _notes_from_html(page.content()):
                found.setdefault(n.note_id, n)
        if progress:
            progress(len(found))

        idle, last = 0, len(found)
        while state["has_more"] and idle < max_idle_rounds:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1800)
            if len(found) == last:
                idle += 1
            else:
                idle, last = 0, len(found)
                if progress:
                    progress(last)
        browser.close()
    return list(found.values())


def fetch_notes_all(cookie: str, user_id: str, user_agent: str, headless: bool = True,
                    progress: Callable[[int], None] | None = None, max_idle_rounds: int = 4) -> list[NoteItem]:
    """Playwright 自动翻页拿全部笔记。放在独立线程里跑，避免和宿主（如 Streamlit）的事件循环冲突。"""
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_fetch_all_in_thread, cookie, user_id, user_agent, headless, progress, max_idle_rounds).result()


# ---------------------------------------------------------------- 缓存 / 搜索


def save_cache(notes: Iterable[NoteItem], path: Path = CACHE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(n) for n in notes], ensure_ascii=False, indent=2), encoding="utf-8")


def load_cache(path: Path = CACHE_FILE) -> list[NoteItem]:
    if not path.exists():
        return []
    return [NoteItem(**d) for d in json.loads(path.read_text(encoding="utf-8"))]


def search_notes(notes: Iterable[NoteItem], keyword: str) -> list[NoteItem]:
    kw = keyword.strip().lower()
    if not kw:
        return list(notes)
    return [n for n in notes if kw in n.display_title.lower()]


# ---------------------------------------------------------------- 下载


@dataclass
class DownloadResult:
    note_id: str
    title: str
    dir: str
    files: list[str]
    error: str = ""


def download_note(client: XhsClient, note: NoteItem, save_dir: str | Path) -> DownloadResult:
    """下载一篇笔记：图片/视频 + 文字（标题、正文、话题、互动数据）到 save_dir/<标题>/。"""
    try:
        detail = client.get_note_by_id_from_html(note.note_id, note.xsec_token)
    except Exception as e:  # noqa: BLE001
        return DownloadResult(note.note_id, note.display_title, "", [], f"获取详情失败: {e}")

    title = get_valid_path_name(detail.get("title", "")).strip() or note.note_id
    note_dir = Path(save_dir) / title
    note_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []

    desc = detail.get("desc", "")
    tags = " ".join(f"#{t.get('name', '')}" for t in detail.get("tag_list", []) if t.get("name"))
    interact = detail.get("interact_info", {})
    txt = note_dir / f"{title}.txt"
    with open(txt, "w", encoding="utf-8") as f:
        f.write(f"标题: {detail.get('title', '')}\n\n")
        if desc:
            f.write(f"{desc}\n\n")
        if tags:
            f.write(f"{tags}\n\n")
        f.write(
            f"点赞: {interact.get('liked_count', 0)}  收藏: {interact.get('collected_count', 0)}  "
            f"评论: {interact.get('comment_count', 0)}\n"
        )
        f.write(f"笔记ID: {note.note_id}\n类型: {detail.get('type', 'unknown')}\n")
    files.append(str(txt))

    try:
        if detail.get("type") == "video":
            url = get_video_url_from_note(detail)
            if url:
                out = note_dir / f"{title}.mp4"
                download_file(url, str(out))
                files.append(str(out))
        else:
            for i, url in enumerate(get_imgs_url_from_note(detail)):
                out = note_dir / f"{title}_{i}.png"
                download_file(url, str(out))
                files.append(str(out))
    except Exception as e:  # noqa: BLE001
        return DownloadResult(note.note_id, title, str(note_dir), files, f"媒体下载失败: {e}")

    return DownloadResult(note.note_id, title, str(note_dir), files)


def download_many(client: XhsClient, notes: Iterable[NoteItem], save_dir: str | Path,
                  interval: float = 1.0, progress: Callable[[int, int, DownloadResult], None] | None = None
                  ) -> list[DownloadResult]:
    notes = list(notes)
    results = []
    for i, n in enumerate(notes, 1):
        r = download_note(client, n, save_dir)
        results.append(r)
        if progress:
            progress(i, len(notes), r)
        if i < len(notes):
            time.sleep(interval)
    return results
