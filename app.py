"""xhs-studio Streamlit 界面：streamlit run app.py"""

from __future__ import annotations

import tempfile
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from xhs_studio import __version__
from xhs_studio.client import check_login, detect_user_id, make_client
from xhs_studio.config import CACHE_FILE, CONFIG_FILE, Settings
from xhs_studio.notes import (
    NoteItem, download_many, fetch_notes_all, fetch_notes_quick, load_cache, save_cache, search_notes,
)
from xhs_studio.publish import publish_image_note, publish_video_note, resolve_topics, search_topic

st.set_page_config(page_title="xhs-studio", page_icon="📕", layout="wide")

st.markdown(
    """
    <style>
      .block-container { padding-top: 2rem; max-width: 1100px; }
      h1, h2, h3 { letter-spacing: -0.01em; }
      .xs-muted { color: #8a8a8a; font-size: 0.85rem; }
      .xs-pill { display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.75rem;
                 background:#f3f0ea; color:#5a5a5a; margin-right:6px; }
      .xs-pill.ok { background:#e6f4ea; color:#1e6b3a; }
      .xs-pill.bad { background:#fdecea; color:#a12a22; }
      div[data-testid="stSidebar"] { background: #faf8f4; }
      button[kind="primary"] { background:#c6403a; border-color:#c6403a; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- state

def _init():
    ss = st.session_state
    if "settings" not in ss:
        ss.settings = Settings.load()
    if "client" not in ss:
        ss.client = None
        if ss.settings.cookie:
            try:
                ss.client = make_client(ss.settings.cookie)
            except ValueError:
                ss.client = None
    if "notes" not in ss:
        ss.notes = load_cache()
        ss.notes_source = "缓存" if ss.notes else ""
    if "keyword" not in ss:
        ss.keyword = ""


def _rebuild_client():
    ss = st.session_state
    try:
        ss.client = make_client(ss.settings.cookie)
    except ValueError as e:
        ss.client = None
        st.error(str(e))


_init()
S: Settings = st.session_state.settings


# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.markdown("## 📕 xhs-studio")
    st.markdown('<div class="xs-muted">小红书笔记备份 · 发布工作台</div>', unsafe_allow_html=True)
    st.markdown("")
    page = st.radio("页面", ["笔记", "发布", "设置"], label_visibility="collapsed")
    st.markdown("---")
    ok = S.ready and st.session_state.client is not None
    st.markdown(
        f'<span class="xs-pill {"ok" if ok else "bad"}">{"已配置" if ok else "未配置"}</span>'
        f'<span class="xs-pill">{len(st.session_state.notes)} 篇笔记</span>',
        unsafe_allow_html=True,
    )
    if S.user_id:
        st.markdown(f'<div class="xs-muted">user_id: <code>{S.user_id}</code></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="xs-muted" style="margin-top:2rem">v{__version__} · 基于 '
                f'<a href="https://github.com/ReaJason/xhs">ReaJason/xhs</a></div>', unsafe_allow_html=True)


def _need_setup() -> bool:
    if S.ready and st.session_state.client is not None:
        return False
    st.info("先到「设置」页填入 Cookie，识别到 user_id 后即可使用。")
    return True


# ---------------------------------------------------------------- 笔记页

def page_notes():
    st.markdown("## 笔记")
    if _need_setup():
        return
    ss = st.session_state
    client = ss.client

    c1, c2, c3 = st.columns([1, 1, 3])
    if c1.button("快速刷新", help="抓主页 HTML，只有首屏约 30 篇，秒回", use_container_width=True):
        with st.spinner("抓取主页..."):
            try:
                ss.notes = fetch_notes_quick(client, S.user_id)
                ss.notes_source = "首屏"
                save_cache(ss.notes)
            except Exception as e:  # noqa: BLE001
                st.error(str(e))
    if c2.button("完整刷新", type="primary", help="Playwright 打开主页自动翻页，拿全部笔记", use_container_width=True):
        holder = st.empty()
        counter = {"n": 0}

        def prog(n):
            counter["n"] = n

        holder.info("启动浏览器翻页中，请稍候...")
        try:
            notes = fetch_notes_all(S.cookie, S.user_id, client.user_agent, headless=S.headless, progress=prog)
            ss.notes = notes
            ss.notes_source = "完整"
            save_cache(notes)
            holder.success(f"完成，共 {len(notes)} 篇，已缓存到 {CACHE_FILE}")
        except Exception as e:  # noqa: BLE001
            holder.error(f"翻页失败：{e}\n\n若是首次使用请先执行 `playwright install chromium`；"
                         f"若怀疑触发验证码，可在设置里关闭无头模式观察浏览器。")
    if ss.notes_source:
        c3.markdown(f'<div class="xs-muted" style="padding-top:0.6rem">来源：{ss.notes_source} · '
                    f'{len(ss.notes)} 篇</div>', unsafe_allow_html=True)

    if not ss.notes:
        st.markdown('<div class="xs-muted">还没有笔记列表，点上面的按钮刷新一下。</div>', unsafe_allow_html=True)
        return

    ss.keyword = st.text_input("按标题搜索", ss.keyword, placeholder="输入关键词过滤，留空显示全部")
    hits = search_notes(ss.notes, ss.keyword)
    st.caption(f"匹配 {len(hits)} 篇")

    df = pd.DataFrame(
        [{"选择": False, "标题": n.display_title, "类型": "视频" if n.is_video else "图文", "note_id": n.note_id}
         for n in hits]
    )
    edited = st.data_editor(
        df,
        hide_index=True,
        use_container_width=True,
        height=min(520, 40 + 35 * max(len(df), 1)),
        column_config={
            "选择": st.column_config.CheckboxColumn(width="small"),
            "标题": st.column_config.TextColumn(width="large", disabled=True),
            "类型": st.column_config.TextColumn(width="small", disabled=True),
            "note_id": st.column_config.TextColumn(width="medium", disabled=True),
        },
        key="notes_table",
    )
    selected_ids = set(edited.loc[edited["选择"], "note_id"]) if len(edited) else set()
    selected = [n for n in hits if n.note_id in selected_ids]

    d1, d2, d3 = st.columns([1, 1, 3])
    do_sel = d1.button(f"下载选中 ({len(selected)})", disabled=not selected, use_container_width=True)
    do_all = d2.button(f"下载全部匹配 ({len(hits)})", disabled=not hits, use_container_width=True)
    d3.markdown(f'<div class="xs-muted" style="padding-top:0.6rem">保存到 <code>{S.save_dir}</code></div>',
                unsafe_allow_html=True)

    targets = selected if do_sel else hits if do_all else []
    if targets:
        bar = st.progress(0.0)
        log = st.container()
        results = []

        def prog(i, total, r):
            bar.progress(i / total, text=f"{i}/{total}  {r.title}")
            with log:
                if r.error:
                    st.markdown(f"❌ **{r.title}** — {r.error}")
                else:
                    st.markdown(f"✅ **{r.title}** — {len(r.files)} 个文件")
            results.append(r)

        download_many(client, targets, S.save_dir, S.request_interval, prog)
        ok = sum(1 for r in results if not r.error)
        bar.progress(1.0, text=f"完成：成功 {ok}/{len(results)}")


# ---------------------------------------------------------------- 发布页

def _save_uploads(files, folder: Path) -> list[str]:
    out = []
    for f in files:
        p = folder / f.name
        p.write_bytes(f.getbuffer())
        out.append(str(p))
    return out


def _topics_input(key: str):
    raw = st.text_input("话题（逗号分隔，可留空）", key=f"{key}_topics", placeholder="例如：投资理财, 复利")
    names = [x.strip().lstrip("#") for x in raw.replace("，", ",").split(",") if x.strip()]
    if names and st.button("预览话题匹配", key=f"{key}_topics_btn"):
        for name in names:
            hits = search_topic(st.session_state.client, name, limit=3)
            if hits:
                st.markdown(f"**{name}** → " + " · ".join(f"`{h.name}`" for h in hits) + "（取第一个）")
            else:
                st.markdown(f"**{name}** → 未找到，发布时会跳过")
    return names


def _schedule_input(key: str):
    if not st.checkbox("定时发布", key=f"{key}_sched"):
        return None
    c1, c2 = st.columns(2)
    d = c1.date_input("日期", key=f"{key}_date")
    t = c2.time_input("时间", key=f"{key}_time")
    return datetime.combine(d, t).strftime("%Y-%m-%d %H:%M:%S")


def _visibility_input(key: str) -> bool:
    private = st.toggle("私密发布（仅自己可见）", value=True, key=f"{key}_private")
    if not private:
        st.warning("这条笔记会**公开**发布到你的账号。")
    return private


def _show_result(r, private: bool):
    st.success(f"发布成功{'（私密）' if private else ''}，note_id = `{r.note_id}`")
    if r.note_id:
        st.markdown(f"https://www.xiaohongshu.com/explore/{r.note_id}")


def page_publish():
    st.markdown("## 发布")
    if _need_setup():
        return
    client = st.session_state.client
    tab_img, tab_vid = st.tabs(["图文笔记", "视频笔记"])

    with tab_img:
        title = st.text_input("标题", key="img_title", max_chars=20, placeholder="20 字以内")
        desc = st.text_area("正文", key="img_desc", height=200, placeholder="正文内容")
        files = st.file_uploader("图片（可多选，按顺序）", type=["jpg", "jpeg", "png"],
                                 accept_multiple_files=True, key="img_files")
        if files:
            st.image([f.getvalue() for f in files], width=140)
        topics = _topics_input("img")
        post_time = _schedule_input("img")
        private = _visibility_input("img")
        if st.button("发布图文", type="primary", disabled=not (title and files), key="img_go"):
            tmp = Path(tempfile.mkdtemp(prefix="xhs-studio-"))
            paths = _save_uploads(files, tmp)
            with st.spinner("上传图片并创建笔记..."):
                try:
                    t = resolve_topics(client, topics)
                    r = publish_image_note(client, title, desc, paths, t, post_time, is_private=private)
                    _show_result(r, private)
                except Exception as e:  # noqa: BLE001
                    st.error(f"发布失败：{e}")

    with tab_vid:
        title = st.text_input("标题", key="vid_title", max_chars=20, placeholder="20 字以内")
        desc = st.text_area("正文", key="vid_desc", height=200)
        video = st.file_uploader("视频（mp4）", type=["mp4", "mov"], key="vid_file")
        cover = st.file_uploader("封面（可选，不传则用视频首帧）", type=["jpg", "jpeg", "png"], key="vid_cover")
        if cover:
            st.image(cover.getvalue(), width=140)
        topics = _topics_input("vid")
        post_time = _schedule_input("vid")
        private = _visibility_input("vid")
        if st.button("发布视频", type="primary", disabled=not (title and video), key="vid_go"):
            tmp = Path(tempfile.mkdtemp(prefix="xhs-studio-"))
            vpath = _save_uploads([video], tmp)[0]
            cpath = _save_uploads([cover], tmp)[0] if cover else None
            with st.spinner("上传视频（大文件会分片）并创建笔记，可能需要一两分钟..."):
                try:
                    t = resolve_topics(client, topics)
                    r = publish_video_note(client, title, desc, vpath, cpath, t, post_time, is_private=private)
                    _show_result(r, private)
                except Exception as e:  # noqa: BLE001
                    st.error(f"发布失败：{e}")


# ---------------------------------------------------------------- 设置页

def page_settings():
    st.markdown("## 设置")
    st.markdown(
        '<div class="xs-muted">Cookie 的获取：浏览器登录 xiaohongshu.com 与 creator.xiaohongshu.com 后，'
        '开发者工具 → Network → 任意请求 → Request Headers → 复制整个 Cookie。'
        f'配置只保存在本机 <code>{CONFIG_FILE}</code>。</div>',
        unsafe_allow_html=True,
    )
    st.markdown("")
    cookie = st.text_area("Cookie", S.cookie, height=140)
    c1, c2 = st.columns(2)
    user_id = c1.text_input("user_id（留空自动识别）", S.user_id)
    save_dir = c2.text_input("下载目录", S.save_dir)
    c3, c4 = st.columns(2)
    headless = c3.toggle("完整刷新时隐藏浏览器窗口（无头模式）", S.headless)
    interval = c4.number_input("下载间隔（秒）", 0.0, 10.0, float(S.request_interval), 0.5)

    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("保存", type="primary", use_container_width=True):
        S.cookie, S.user_id, S.save_dir, S.headless, S.request_interval = (
            cookie.strip(), user_id.strip(), save_dir.strip(), headless, float(interval))
        _rebuild_client()
        if st.session_state.client and not S.user_id:
            S.user_id = detect_user_id(st.session_state.client, S.cookie)
        S.save()
        if S.user_id:
            st.success(f"已保存，user_id = {S.user_id}")
        else:
            st.warning("已保存，但没能自动识别 user_id：请登录一次创作者平台再复制 cookie，或手动填写。")
        time.sleep(0.6)
        st.rerun()
    if b2.button("测试连接", use_container_width=True, disabled=st.session_state.client is None):
        info = check_login(st.session_state.client)
        if info:
            name = info.get("nickname") or info.get("name") or ""
            st.success(f"创作者平台连接正常{('：' + name) if name else ''}")
        else:
            st.error("创作者平台接口不通，cookie 可能已过期")


{"笔记": page_notes, "发布": page_publish, "设置": page_settings}[page]()
