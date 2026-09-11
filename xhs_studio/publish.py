"""图文 / 视频发布（创作者平台接口，内置签名实测可用）。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from xhs import XhsClient


@dataclass
class TopicInfo:
    id: str
    name: str
    link: str = ""

    def as_hash_tag(self) -> dict:
        return {"id": self.id, "name": self.name, "type": "topic", "link": self.link}


@dataclass
class PublishResult:
    note_id: str
    raw: dict = field(default_factory=dict)


def search_topic(client: XhsClient, keyword: str, limit: int = 10) -> list[TopicInfo]:
    """话题联想搜索，返回候选列表（第一个通常是精确匹配 / 最热）。"""
    res = client.get_suggest_topic(keyword) or []
    return [TopicInfo(str(t["id"]), t["name"], t.get("link", "")) for t in res[:limit]]


def resolve_topics(client: XhsClient, names: list[str]) -> list[TopicInfo]:
    out = []
    for name in names:
        name = name.strip().lstrip("#")
        if not name:
            continue
        hits = search_topic(client, name, limit=1)
        if hits:
            out.append(hits[0])
    return out


def with_topic_marks(desc: str, topics: list[TopicInfo]) -> str:
    """小红书要求正文里带 #话题名[话题]# 标记，话题才会渲染成可点击标签。"""
    if not topics:
        return desc
    marks = " ".join(f"#{t.name}[话题]#" for t in topics)
    return desc.rstrip() + "\n\n" + marks


def _check_files(paths: list[str]) -> None:
    for p in paths:
        if not os.path.exists(p):
            raise FileNotFoundError(p)


def publish_image_note(client: XhsClient, title: str, desc: str, images: list[str],
                       topics: list[TopicInfo] | None = None, post_time: str | None = None,
                       is_private: bool = True) -> PublishResult:
    _check_files(images)
    topics = topics or []
    res = client.create_image_note(
        title, with_topic_marks(desc, topics), images,
        post_time=post_time, topics=[t.as_hash_tag() for t in topics], is_private=is_private,
    )
    return _to_result(res)


def publish_video_note(client: XhsClient, title: str, desc: str, video_path: str,
                       cover_path: str | None = None, topics: list[TopicInfo] | None = None,
                       post_time: str | None = None, is_private: bool = True) -> PublishResult:
    _check_files([video_path] + ([cover_path] if cover_path else []))
    topics = topics or []
    res = client.create_video_note(
        title, video_path, with_topic_marks(desc, topics), cover_path=cover_path,
        post_time=post_time, topics=[t.as_hash_tag() for t in topics], is_private=is_private,
    )
    return _to_result(res)


def _to_result(res) -> PublishResult:
    if isinstance(res, dict):
        return PublishResult(str(res.get("id", "")), res)
    try:
        data = json.loads(res) if isinstance(res, str) else {}
    except json.JSONDecodeError:
        data = {}
    return PublishResult(str(data.get("id", "")), data or {"raw": str(res)})
