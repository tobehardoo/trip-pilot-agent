"""B站 分享（专栏文章 / 视频）→ 标题 + 简介正文。

- 短链 b23.tv 先跟随重定向拿到真实地址。
- 专栏 `read/cvN`：用 `x/article/view` 取富文本正文。
- 视频 `video/BVxxx`：用 `x/web-interface/view` 取标题 + 简介(desc)。
视频本身没有完整文章，简介即可用正文；若简介为空则 MEDIA_ONLY。
"""

from __future__ import annotations

import json
import re
import time

import httpx

from ..errors import LinkParseError
from ..models import ParsedLink
from ..util import strip_html

_ARTICLE_ID = re.compile(r"read/cv(?P<id>\d+)")
_VIDEO = re.compile(r"video/(?:av(?P<aid>\d+)|BV(?P<bvid>[A-Za-z0-9]+))", re.I)
_SPI_URL = "https://api.bilibili.com/x/frontend/finger/spi"
_API_HEADERS = {
    # B站 view API 若带手机 UA 可能被反爬拦；用桌面版请求。
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


def matches(url: str) -> bool:
    lowered = url.lower()
    return "bilibili.com" in lowered or "b23.tv" in lowered


async def parse(client, url: str) -> ParsedLink:
    real = url
    if "b23.tv" in url.lower():
        try:
            resp = await client.get(
                url, follow_redirects=True, headers=_API_HEADERS
            )
        except httpx.HTTPError as error:
            raise LinkParseError.network(str(error)) from error
        # 最终页可能被 412 反爬拦截，但重定向 URL 已包含真实 BV/资源，足够定位。
        real = str(resp.url)

    article = _ARTICLE_ID.search(real)
    if article:
        return await _parse_article(client, real, article.group("id"))
    video = _VIDEO.search(real)
    if video:
        return await _parse_video(client, real, video)
    raise LinkParseError.unsupported_platform("B站")


async def _parse_article(client, original: str, article_id: str) -> ParsedLink:
    api = f"https://api.bilibili.com/x/article/view?id={article_id}"
    resp = await _get_json(client, api)
    if resp is None:
        raise LinkParseError.parse_failed("B站专栏返回异常")
    title = (resp.get("title") or "").strip()
    content = strip_html(resp.get("content") or "")
    if not content:
        raise LinkParseError.parse_failed("B站专栏无正文")
    author = ""
    if isinstance(resp.get("author"), dict):
        author = resp["author"].get("name") or ""
    desc = f"{title}\n{content}" if title and not content.startswith(title) else content
    return ParsedLink(platform="bilibili", title=title, desc=desc, author=author, url=original)


async def _parse_video(client, original: str, matched: re.Match[str]) -> ParsedLink:
    try:
        from bilibili_api import video as bili_video

        if matched.group("bvid"):
            # 正则组只捕获 "BV" 之后的 10 位，需要补回前缀
            v = bili_video.Video(bvid="BV" + matched.group("bvid"))
        else:
            v = bili_video.Video(aid=int(matched.group("aid")))
        info = await v.get_info()
        title = (info.get("title") or "").strip()
        desc = (info.get("desc") or "").strip()
        owner = info.get("owner") or {}
        author = owner.get("name") or ""
    except Exception as error:  # noqa: BLE001 - 依赖未装或接口失败
        raise LinkParseError.parse_failed(f"B站视频信息获取失败: {error}") from error
    if not title and not desc:
        raise LinkParseError.parse_failed("B站视频无简介")
    text = f"{title}\n{desc}" if title and desc else (title or desc)
    return ParsedLink(platform="bilibili", title=title, desc=text, author=author, url=original)


async def _get_json(client, api: str):
    await _ensure_buvid(client)
    headers = dict(_API_HEADERS)
    # 带上已注册的 buvid 指纹，避免 view API 返回 412
    buvid3 = client.cookies.get("buvid3")
    if buvid3:
        headers["Cookie"] = f"buvid3={buvid3}; b_nut={client.cookies.get('b_nut') or ''}"
    try:
        resp = await client.get(api, headers=headers)
    except Exception as error:  # noqa: BLE001
        raise LinkParseError.network(str(error)) from error
    if resp.status_code != 200:
        raise LinkParseError.parse_failed(f"B站接口请求失败 HTTP {resp.status_code}")
    try:
        body = resp.json()
    except json.JSONDecodeError:
        raise LinkParseError.parse_failed("B站接口返回非 JSON") from None
    if body.get("code") not in (0, None) or not isinstance(body.get("data"), dict):
        raise LinkParseError.parse_failed(f"B站接口返回异常: {body.get('message')}")
    return body["data"]


async def _ensure_buvid(client) -> None:
    """若客户端还没有 buvid 指纹 cookie，向 B站的指纹接口注册。"""
    if client.cookies.get("buvid3"):
        return
    try:
        resp = await client.get(_SPI_URL, headers=_API_HEADERS)
        if resp.status_code != 200:
            return
        data = (resp.json().get("data") or {})
        b3 = data.get("b_3")
        b4 = data.get("b_4")
        if b3:
            client.cookies.set("buvid3", b3)
        if b4:
            client.cookies.set("buvid4", b4)
        client.cookies.set("b_nut", str(int(time.time() * 1000)))
    except Exception:  # noqa: BLE001 - 拿不到指纹时退化为无指纹请求
        return