"""微博分享 → 标题 + 正文。

技术：用 XHR 头 + 时间戳参数直接请求 `m.weibo.cn/statuses/show?id=..`，
解析 JSON 的 text（HTML）取正文。移植自 astrbot_plugin_parser（MIT）。
"""

from __future__ import annotations

import json
import re
import time

from ..errors import LinkParseError
from ..models import ParsedLink
from ..util import strip_html

_WID = re.compile(r"weibo(?:\.cn|\.com)/\d+/([0-9a-zA-Z]+)")
_TV_MID = re.compile(r"weibo\.com/tv/show/\d{4}:\d+\?mid=(?P<mid>\d+)")
_ARTICLE_ID = re.compile(r"weibo\.com/ttarticle/(?:m/)?show#?/?(?:id=)?(?P<id>\d+)")
_STATUS = re.compile(r"weibo\.cn/(?:status|detail)/\d+/([0-9a-zA-Z]+)")


def matches(url: str) -> bool:
    lowered = url.lower()
    return "weibo.com" in lowered or "weibo.cn" in lowered


async def parse(client, url: str) -> ParsedLink:
    if _ARTICLE_ID.search(url):
        raise LinkParseError.unsupported_platform("微博长文")
    wid = _extract_wid(url)
    if not wid:
        raise LinkParseError.unsupported_platform("微博")
    headers = {
        "accept": "application/json, text/plain, */*",
        "referer": f"https://m.weibo.cn/detail/{wid}",
        "origin": "https://m.weibo.cn",
        "x-requested-with": "XMLHttpRequest",
        "mweibo-pwa": "1",
    }
    ts = int(time.time() * 1000)
    try:
        resp = await client.get(
            f"https://m.weibo.cn/statuses/show?id={wid}&_={ts}",
            headers=headers,
            follow_redirects=False,
        )
    except Exception as error:  # noqa: BLE001 - 网络类
        raise LinkParseError.network(str(error)) from error
    if resp.status_code != 200:
        if resp.status_code in {403, 418}:
            raise LinkParseError.needs_auth()
        raise LinkParseError.parse_failed(f"HTTP {resp.status_code}")
    try:
        data = resp.json()["data"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise LinkParseError.parse_failed("微博返回数据异常") from None

    body = strip_html(data.get("text") or "")
    if not body:
        raise LinkParseError.parse_failed("微博无正文")
    user = data.get("user") or {}
    page_info = data.get("page_info") or {}
    title = (page_info.get("title") or "") if isinstance(page_info, dict) else ""
    return ParsedLink(
        platform="weibo",
        title=title or body[:80],
        desc=body,
        author=user.get("screen_name") or "",
        url=url,
    )


def _extract_wid(url: str) -> str | None:
    for pattern in (_WID, _STATUS):
        matched = pattern.search(url)
        if matched:
            return matched.group(1)
    return None