"""快手分享 → 标题（caption）。

技术：跟随重定向到图文/视频页，解析 `window.INIT_STATE=(...)` 里的
``photo.caption`` 作为标题。移植自 astrbot_plugin_parser（MIT）。
"""

from __future__ import annotations

from ..errors import LinkParseError
from ..models import ParsedLink
from ..util import extract_embedded_json, fetch_text


def matches(url: str) -> bool:
    lowered = url.lower()
    return "kuaishou.com" in lowered or "chenzhongtech.com" in lowered


async def parse(client, url: str) -> ParsedLink:
    headers = {"Referer": "https://v.kuaishou.com/"}
    html, final = await fetch_text(client, url, headers=headers)
    state = extract_embedded_json(html, "INIT_STATE")
    caption = _first_caption(state)
    if not caption:
        raise LinkParseError.media_only()
    return ParsedLink(
        platform="kuaishou", title=caption, desc=caption, url=final
    )


def _first_caption(state: dict | None) -> str:
    if not state:
        return ""
    for value in state.values():
        if not isinstance(value, dict):
            continue
        photo = value.get("photo")
        if isinstance(photo, dict):
            caption = photo.get("caption")
            if isinstance(caption, str) and caption.strip():
                return caption.strip()
    return ""