"""构造 XhsClient。

上游 ReaJason/xhs 的 XhsClient 在没有传 sign 函数时，主站接口会直接报错；
这里把库内置的纯 Python 签名 (xhs.help.sign) 包装成 external_sign 传入。

实测（2026-09）：
- 创作者平台相关接口（上传许可、上传文件、创建笔记、话题搜索）用内置签名可用；
- 主站接口（selfinfo、user_posted 等）内置签名会返回 {'code': -1}，
  因此笔记列表 / 详情走的是页面 HTML 与 Playwright 抓包，见 notes.py。
"""

from __future__ import annotations

from xhs import XhsClient
from xhs import help as xhs_help

from .config import cookie_to_dict


def _builtin_sign(uri, data=None, a1="", web_session=""):
    return xhs_help.sign(uri, data, a1=a1)


def make_client(cookie: str, timeout: int = 15) -> XhsClient:
    if not cookie or "a1=" not in cookie:
        raise ValueError("cookie 为空或缺少 a1 字段，请从浏览器重新复制完整 Cookie")
    return XhsClient(cookie, sign=_builtin_sign, timeout=timeout)


def detect_user_id(client: XhsClient, cookie: str) -> str:
    """尽量自动识别当前账号的 user_id。"""
    d = cookie_to_dict(cookie)
    for k, v in d.items():
        if k.startswith("x-user-id"):
            return v
    try:
        info = client.get_self_info_from_creator()
        for key in ("userId", "user_id", "red_id", "id"):
            if isinstance(info, dict) and info.get(key):
                return str(info[key])
    except Exception:
        pass
    return ""


def check_login(client: XhsClient) -> dict | None:
    """用创作者平台接口探测 cookie 是否有效；失败返回 None。"""
    try:
        info = client.get_self_info_from_creator()
        return info if isinstance(info, dict) else {"raw": info}
    except Exception:
        return None
