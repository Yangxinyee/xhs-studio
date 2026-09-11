"""本地配置：cookie、用户 ID、下载目录等。

配置目录的查找顺序：
1. 环境变量 XHS_STUDIO_HOME
2. 项目根目录（如果那里已经有 config.json —— 该文件在 .gitignore 里，不会被提交）
3. ~/.xhs-studio（默认）

也可以用环境变量 XHS_COOKIE 覆盖 cookie。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _resolve_config_dir() -> Path:
    env = os.environ.get("XHS_STUDIO_HOME")
    if env:
        return Path(env)
    if (PROJECT_DIR / "config.json").exists():
        return PROJECT_DIR
    return Path.home() / ".xhs-studio"


CONFIG_DIR = _resolve_config_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"
CACHE_FILE = CONFIG_DIR / "notes_cache.json"


@dataclass
class Settings:
    cookie: str = ""
    user_id: str = ""
    save_dir: str = str(Path.home() / "xhs-notes")
    headless: bool = True
    request_interval: float = 1.0
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        data = {}
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        s = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        env_cookie = os.environ.get("XHS_COOKIE")
        if env_cookie:
            s.cookie = env_cookie
        if not s.user_id and s.cookie:
            s.user_id = user_id_from_cookie(s.cookie)
        return s

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def ready(self) -> bool:
        return bool(self.cookie and self.user_id)


def cookie_to_dict(cookie: str) -> dict:
    out = {}
    for block in cookie.split(";"):
        if "=" in block:
            k, v = block.strip().split("=", 1)
            out[k] = v
    return out


def user_id_from_cookie(cookie: str) -> str:
    """创作者平台登录后 cookie 里会带 x-user-id-creator.xiaohongshu.com，直接取。"""
    d = cookie_to_dict(cookie)
    for k, v in d.items():
        if k.startswith("x-user-id"):
            return v
    return ""
