"""命令行入口：python -m xhs_studio.cli <command>

  config   --cookie "..." [--user-id ...] [--save-dir ...]
  list     [--all] [--no-headless]
  search   <关键词>
  download [--all | --title <关键词> | --id <note_id> ...]
  publish-image --title ... --desc ... --image a.jpg [--image b.jpg] [--topic 话题] [--public] [--at "2026-09-12 10:00:00"]
  publish-video --title ... --desc ... --video a.mp4 [--cover c.jpg] [--topic 话题] [--public] [--at ...]
"""

from __future__ import annotations

import argparse
import sys

from .client import detect_user_id, make_client
from .config import Settings
from .notes import download_many, fetch_notes_all, fetch_notes_quick, load_cache, save_cache, search_notes
from .publish import publish_image_note, publish_video_note, resolve_topics


def _client_and_settings():
    s = Settings.load()
    if not s.cookie:
        sys.exit("未配置 cookie，先运行: python -m xhs_studio.cli config --cookie '...'")
    c = make_client(s.cookie)
    if not s.user_id:
        s.user_id = detect_user_id(c, s.cookie)
        if not s.user_id:
            sys.exit("无法识别 user_id，请用 config --user-id 手动指定")
        s.save()
    return c, s


def _print(notes):
    for i, n in enumerate(notes, 1):
        print(f"{i:>4}. [{n.type:<6}] {n.display_title}  ({n.note_id})")


def cmd_config(a):
    s = Settings.load()
    if a.cookie:
        s.cookie = a.cookie
    if a.user_id:
        s.user_id = a.user_id
    if a.save_dir:
        s.save_dir = a.save_dir
    if a.cookie and not a.user_id:
        s.user_id = detect_user_id(make_client(s.cookie), s.cookie)
    s.save()
    print(f"已保存。user_id={s.user_id or '(未识别)'}  save_dir={s.save_dir}")


def cmd_list(a):
    c, s = _client_and_settings()
    if a.all:
        notes = fetch_notes_all(s.cookie, s.user_id, c.user_agent, headless=not a.no_headless,
                                progress=lambda n: print(f"  已获取 {n} 篇...", flush=True))
        save_cache(notes)
    else:
        notes = fetch_notes_quick(c, s.user_id)
    _print(notes)
    print(f"共 {len(notes)} 篇" + ("（已缓存）" if a.all else "（仅首屏，--all 取全部）"))


def cmd_search(a):
    notes = load_cache()
    if not notes:
        sys.exit("还没有缓存，先运行 list --all")
    hits = search_notes(notes, a.keyword)
    _print(hits)
    print(f"匹配 {len(hits)} 篇")


def cmd_download(a):
    c, s = _client_and_settings()
    notes = load_cache() or fetch_notes_quick(c, s.user_id)
    if a.id:
        notes = [n for n in notes if n.note_id in a.id]
    elif a.title:
        notes = search_notes(notes, a.title)
    elif not a.all:
        sys.exit("请指定 --all / --title / --id")
    if not notes:
        sys.exit("没有匹配的笔记")
    print(f"开始下载 {len(notes)} 篇 → {s.save_dir}")

    def prog(i, total, r):
        status = "失败: " + r.error if r.error else f"{len(r.files)} 个文件"
        print(f"[{i}/{total}] {r.title}  {status}")

    download_many(c, notes, s.save_dir, s.request_interval, prog)


def _publish_common(a, c):
    topics = resolve_topics(c, a.topic or [])
    for t in topics:
        print(f"  话题: {t.name} ({t.id})")
    return topics


def cmd_publish_image(a):
    c, _ = _client_and_settings()
    topics = _publish_common(a, c)
    r = publish_image_note(c, a.title, a.desc, a.image, topics, a.at, is_private=not a.public)
    print("发布成功，note_id =", r.note_id, "" if a.public else "（私密）")


def cmd_publish_video(a):
    c, _ = _client_and_settings()
    topics = _publish_common(a, c)
    r = publish_video_note(c, a.title, a.desc, a.video, a.cover, topics, a.at, is_private=not a.public)
    print("发布成功，note_id =", r.note_id, "" if a.public else "（私密）")


def main(argv=None):
    p = argparse.ArgumentParser(prog="xhs-studio", description="小红书笔记备份与发布")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("config"); sp.add_argument("--cookie"); sp.add_argument("--user-id"); sp.add_argument("--save-dir")
    sp.set_defaults(fn=cmd_config)

    sp = sub.add_parser("list"); sp.add_argument("--all", action="store_true"); sp.add_argument("--no-headless", action="store_true")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("search"); sp.add_argument("keyword"); sp.set_defaults(fn=cmd_search)

    sp = sub.add_parser("download")
    sp.add_argument("--all", action="store_true"); sp.add_argument("--title"); sp.add_argument("--id", nargs="*")
    sp.set_defaults(fn=cmd_download)

    for name, fn in (("publish-image", cmd_publish_image), ("publish-video", cmd_publish_video)):
        sp = sub.add_parser(name)
        sp.add_argument("--title", required=True); sp.add_argument("--desc", required=True)
        if name == "publish-image":
            sp.add_argument("--image", action="append", required=True)
        else:
            sp.add_argument("--video", required=True); sp.add_argument("--cover")
        sp.add_argument("--topic", action="append"); sp.add_argument("--public", action="store_true")
        sp.add_argument("--at", help="定时发布 'YYYY-MM-DD HH:MM:SS'")
        sp.set_defaults(fn=fn)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
