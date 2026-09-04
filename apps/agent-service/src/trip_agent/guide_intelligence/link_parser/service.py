"""分享链接解析入口：识别平台 → 提取正文 → 结构化错误。"""

from __future__ import annotations

import httpx

from . import parsers
from .detect import detect
from .errors import LinkParseError
from .models import ParsedLink

_EXTRACTORS: dict[str, object] = {
    "xhs": parsers.xhs,
    "douyin": parsers.douyin,
    "weibo": parsers.weibo,
    "zhihu": parsers.zhihu,
    "kuaishou": parsers.kuaishou,
    "bilibili": parsers.bilibili,
}


async def parse_link(client: httpx.AsyncClient, url: str) -> ParsedLink:
    """解析一个分享链接为标题+正文；不支持/失败抛 ``LinkParseError``。"""
    detection = detect(url)
    if detection is None:
        raise LinkParseError.unsupported_platform("未知")
    if not detection.is_supported:
        hint = (f"。{detection.hint}" if detection.hint else "")
        raise LinkParseError.unsupported_platform(detection.label + hint)
    module = _EXTRACTORS[detection.extractor]  # type: ignore[index]
    return await module.parse(client, url)


def looks_supported(url: str) -> bool:
    """URL 是否命中已实现正文提取的平台（用于 agent 决定是否走链接解析）。"""
    detection = detect(url)
    return detection is not None and detection.is_supported