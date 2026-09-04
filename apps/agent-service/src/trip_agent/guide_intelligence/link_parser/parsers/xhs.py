"""小红书分享链接 → 标题 + 正文(desc)。

技术：跟随重定向后用移动端 UA + XHR 头抓 `/explore/{id}`，解析
`window.__INITIAL_STATE__` 里的 `note.noteDetailMap[id].note` 取 title/desc。
移植自 astrbot_plugin_parser（MIT）。
"""

from __future__ import annotations

import json
import re

import httpx

from ..errors import LinkParseError
from ..models import ParsedLink
from ..util import fetch_text

_SHORT_LINK = re.compile(r"xhslink\.(?:com|cn)/[A-Za-z0-9._?%&+=/#@-]+")
_EXPLORE = re.compile(
    r"(?:explore|discovery/item)/(?P<query>[0-9A-Za-z]+\?[A-Za-z0-9._%&+=/#@-]+)",
    re.I,
)
_ITEM_ID = re.compile(r"(?:explore|discovery/item)/(?P<id>[0-9A-Za-z]+)", re.I)


def matches(url: str) -> bool:
    return bool(_SHORT_LINK.search(url) or _ITEM_ID.search(url))


def _xhs_headers(ui: dict[str, str]) -> dict[str, str]:
    headers = {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
            "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
        ),
        "origin": "https://www.xiaohongshu.com",
        "x-requested-with": "XMLHttpRequest",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }
    headers.update(ui)
    return headers


def _extract_initial_state(html: str) -> dict:
    matched = re.search(r"window\.__INITIAL_STATE__=(.*?)</script>", html, re.DOTALL)
    if not matched:
        raise LinkParseError.expired()
    text = matched.group(1).replace("undefined", "null").strip()
    return json.loads(text)


async def parse(client: httpx.AsyncClient, url: str) -> ParsedLink:
    ui = dict(client.headers)
    ui.pop("user-agent", None)
    headers = _xhs_headers(ui)

    if short := _SHORT_LINK.search(url):
        final = await _resolve_short(client, short.group(0), headers)
        item_id = _ITEM_ID.search(final)
        if not item_id:
            raise LinkParseError.parse_failed("短链未解析到笔记ID")
        return await _parse_explore(client, final, item_id.group("id"), headers)

    item_id = _ITEM_ID.search(url)
    if not item_id:
        raise LinkParseError.unsupported_platform("小红书")
    return await _parse_explore(client, url, item_id.group("id"), headers)


async def _resolve_short(
    client: httpx.AsyncClient, short: str, headers: dict[str, str]
) -> str:
    try:
        resp = await client.get(f"https://{short}", headers=headers, follow_redirects=True)
    except httpx.HTTPError as error:
        raise LinkParseError.network(str(error)) from error
    if resp.status_code >= 400:
        raise LinkParseError.expired()
    return str(resp.url)


async def _parse_explore(
    client: httpx.AsyncClient, url: str, id_: str, headers: dict[str, str]
) -> ParsedLink:
    html, final = await fetch_text(client, url, headers=headers)
    state = _extract_initial_state(html)
    note = _find_note(state, id_)
    if not note:
        raise LinkParseError.parse_failed("页面未找到笔记正文") from None

    title = _s(note, "title")
    desc = _s(note, "desc")
    text_parts = [p for p in (title, desc) if p]
    if not text_parts:
        if (note.get("type") or "").lower() == "video":
            raise LinkParseError.media_only()
        raise LinkParseError.parse_failed("笔记无正文")

    author = ""
    user = note.get("user") or {}
    author = _s(user, "nickname") or _s(user, "nickName")
    return ParsedLink(platform="xhs", title=title, desc=desc, author=author, url=final)


def _s(obj: dict, key: str) -> str:
    value = obj.get(key)
    return value.strip() if isinstance(value, str) else ""


def _find_note(state: dict, id_: str) -> dict | None:
    """兼容 explore(noteDetailMap) 与 discovery(noteData) 两种 __INITIAL_STATE__ 结构。"""
    try:
        note = state["note"]["noteDetailMap"][id_]["note"]
        if isinstance(note, dict):
            return note
    except (KeyError, TypeError):
        pass

    try:
        note_data = state["noteData"]["data"]["noteData"]
        if isinstance(note_data, dict):
            return note_data
    except (KeyError, TypeError):
        pass
    return None