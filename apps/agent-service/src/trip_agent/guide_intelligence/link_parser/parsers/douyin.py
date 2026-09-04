"""抖音分享链接 → 标题/正文(desc)。

技术：先注册匿名 ttwid(bytedance 临时凭证)，再用移动端 UA + cookie 抓
`www.iesdouyin.com/share/{video|note}/{vid}/`，解析 `window._ROUTER_DATA`
里的 `loaderData.video_(id)/page.videoInfoRes.item_list[].desc`。
移植自 astrbot_plugin_parser（MIT）。
"""

from __future__ import annotations

import contextlib
import json
import re

import httpx

from ..errors import LinkParseError
from ..models import ParsedLink
from ..util import fetch_text, resolve_redirect

_TTWID_URL = "https://ttwid.bytedance.com/ttwid/union/register/"
_VID = re.compile(r"(?:video|note)/(?P<vid>\d{10,})")
_IES = re.compile(r"(?:www\.)?iesdouyin\.com/share/(?:slides|video|note)/(?P<vid>\d+)/", re.I)
_DOUYIN = re.compile(r"douyin\.com/(?:video|note)/(?P<vid>\d+)", re.I)
_OUTER_VID = re.compile(r"(?P<vid>\d{18,20})")


def matches(url: str) -> bool:
    return bool(_DOUYIN.search(url) or _IES.search(url) or _OUTER_VID.search(url))


def _mobile_headers() -> dict[str, str]:
    return {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
            "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
        ),
    }


async def _ensure_ttwid(client: httpx.AsyncClient) -> None:
    if "ttwid" in client.cookies:
        return
    try:
        resp = await client.post(
            _TTWID_URL,
            json={
                "region": "cn",
                "aid": 1768,
                "needFid": False,
                "service": "www.iesdouyin.com",
                "union": True,
                "fid": "",
            },
            headers={"Referer": "https://www.iesdouyin.com/"},
        )
    except httpx.HTTPError as error:
        raise LinkParseError.network(str(error)) from error
    if resp.status_code >= 400:
        raise LinkParseError.needs_auth()
    # ttwid cookie 由服务的 Set-Cookie 自动写入 client.cookies。
    try:
        body = resp.json()
    except json.JSONDecodeError:
        body = {}
    callback = body.get("redirect_url") if isinstance(body, dict) else None
    if callback:
        with contextlib.suppress(httpx.HTTPError):
            await client.get(callback, headers={"Referer": "https://www.iesdouyin.com/"})


def _canonical_url(ty: str, vid: str) -> str:
    return f"https://www.iesdouyin.com/share/{ty}/{vid}/"


async def parse(client: httpx.AsyncClient, url: str) -> ParsedLink:
    await _ensure_ttwid(client)

    vid: str | None = _extract_vid(url)
    if vid is None:
        # 短链 v.douyin.com/...：先跟随重定向拿长链，再取视频 ID
        final_url = await resolve_redirect(client, url, headers=_mobile_headers())
        vid = _extract_vid(final_url)
    if vid is None:
        raise LinkParseError.unsupported_platform("抖音")

    share = _canonical_url("video", vid)
    html, final = await fetch_text(
        client, share, headers=_mobile_headers(), allow_redirects=False
    )
    data = extract_router_data(html)
    item = first_video_item(data)
    if item is None:
        raise LinkParseError.parse_failed("抖音页面未返回视频信息")
    desc = (item.get("desc") or "").strip()
    if not desc:
        # 纯视频/图文但无简介 → 无正文可提取
        raise LinkParseError.media_only()
    author = ((item.get("author") or {}).get("nickname") or "")
    return ParsedLink(
        platform="douyin",
        title=desc[:90],
        desc=desc,
        author=author,
        url=final,
    )


def _extract_vid(url: str) -> str | None:
    for pattern in (_IES, _DOUYIN):
        matched = pattern.search(url)
        if matched:
            return matched.group("vid")
    outer = _OUTER_VID.search(url)
    if outer:
        return outer.group("vid")
    return None


def extract_router_data(html: str) -> dict | None:
    matched = re.search(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", html, re.DOTALL)
    if not matched:
        return None
    try:
        return json.loads(matched.group(1).strip())
    except json.JSONDecodeError:
        return None


def first_video_item(data: dict | None) -> dict | None:
    if not data:
        return None
    loader = data.get("loaderData") or {}
    for page_key in ("video_(id)/page", "note_(id)/page"):
        page = loader.get(page_key)
        if not page:
            continue
        info = page.get("videoInfoRes") or {}
        items = info.get("item_list") or []
        if items and isinstance(items[0], dict):
            return items[0]
    return None