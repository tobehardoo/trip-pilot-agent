"""轻量 HTTP 抓取与内嵌 JSON 提取（仅依赖 httpx + 标准库）。

各平台抓正文的核心是用移动端 UA + 若干 XHR 头让服务端把内容 SSR 进页面，
再正则提取 `window.<NAME>=(...)</script>` 里的 JSON。这些技巧移植自 astrbot 解析插件
（https://github.com/Zhalslar/astrbot_plugin_parser ，MIT），此处只保留抓正文所需。
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .errors import LinkParseError

# 移动端 UA 与通用头，来自插件 constants.py。
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1 Edg/132.0.0.0"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/55.0.2883.87 UBrowser/6.2.4098.3 Safari/537.36"
)


def make_client(*, android: bool = False, follow_redirects: bool = True) -> httpx.AsyncClient:
    """构造带基础请求头的异步客户端；调用方负责 `async with` / 复用与关闭。"""
    headers: dict[str, str] = {
        "User-Agent": MOBILE_UA,
    }
    return httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(20.0),
        follow_redirects=follow_redirects,
        trust_env=False,
        http1=True,
        http2=False,
    )


async def fetch_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    extra: dict[str, str] | None = None,
    allow_redirects: bool | None = None,
) -> tuple[str, str]:
    """GET 并返回 ``(文本内容, 最终 URL)``；4xx/网络错误映射为 LinkParseError。"""
    final_headers = dict(headers or {})
    if extra:
        final_headers.update(extra)
    try:
        resp = await client.get(
            url,
            headers=final_headers,
            follow_redirects=allow_redirects,
        )
    except httpx.HTTPError as error:
        raise LinkParseError.network(str(error)) from error
    if resp.status_code >= 400:
        if resp.status_code in {404, 410}:
            raise LinkParseError.expired()
        if resp.status_code in {403, 418}:
            raise LinkParseError.needs_auth()
        raise LinkParseError.network(f"HTTP {resp.status_code}")
    return resp.text, str(resp.url)


async def resolve_redirect(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> str:
    """跟随重定向返回最终 URL（短链 → 长链），失败映射为 LinkParseError。"""
    try:
        resp = await client.get(url, headers=headers, follow_redirects=True)
    except httpx.HTTPError as error:
        raise LinkParseError.network(str(error)) from error
    if resp.status_code >= 400:
        raise LinkParseError.expired()
    return str(resp.url)


def extract_embedded_json(
    html: str,
    marker: str,
    *,
    replace_undefined: bool = True,
) -> dict[str, Any] | None:
    """提取 `window.<marker>=(.*?)</script>` 中的 JSON 对象。

    Java 侧常见 `&&`/`undefined` 需要归一为 null 才能 ``json.loads``。
    """
    pattern = re.compile(
        re.escape(rf"window\.{marker}\s*=") + r"(.*?)</script>", re.DOTALL
    )
    matched = pattern.search(html)
    if not matched:
        return None
    text = matched.group(1).strip().rstrip(";").strip()
    if replace_undefined:
        text = text.replace("undefined", "null")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def get_text(client: httpx.AsyncClient) -> None:
    """占位，避免误用；各平台直接操作自己的 httpx client。"""
    raise NotImplementedError


def strip_html(text: str) -> str:
    """去除富文本 HTML，保留段落分隔；转义实体还原。"""
    import html as _html

    text = text.replace("<br", "\n<br").replace("</p>", "\n").replace("</div>", "\n")
    text = re.sub(r"<[^>]+>", "", text)
    text = _html.unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    cleaned: list[str] = []
    for line in lines:
        if line and (not cleaned or cleaned[-1] != line):
            cleaned.append(line)
    return "\n".join(cleaned).strip()