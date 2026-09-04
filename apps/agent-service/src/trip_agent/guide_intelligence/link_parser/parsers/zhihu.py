"""知乎（回答 / 专栏文章）→ 标题 + 正文。

知乎对服务器抓取有 zse-ck 反爬挑战，需用 curl_cffi 的浏览器 TLS 指纹。
流程：用 curl_cffi impersonate 抓页面 → 解析 `script#js-initialData` 里的
``initialState.entities.answers[id].content``（HTML）转纯文本。
"""

from __future__ import annotations

import asyncio
import json
import re

from ..errors import LinkParseError
from ..models import ParsedLink
from ..util import strip_html

_ARTICLE = re.compile(r"zhuanlan\.zhihu\.com/p/(?P<id>\d+)")
_ANSWER = re.compile(r"zhihu\.com/question/(?P<qid>\d+)/answer/(?P<aid>\d+)")
_QUESTION = re.compile(r"zhihu\.com/question/(?P<id>\d+)(?!.*/answer/(\d+))")

_INITIAL_SCRIPT = re.compile(
    r'<script[^>]*id="js-initialData"[^>]*>(.*?)</script>', re.DOTALL
)


def matches(url: str) -> bool:
    return "zhihu.com" in (url or "").lower()


async def parse(client, url: str) -> ParsedLink:
    answer = _ANSWER.search(url)
    if answer:
        return await _parse_answer_answer(url, answer.group("qid"), answer.group("aid"))
    article = _ARTICLE.search(url)
    if article:
        return await _parse_article(url, article.group("id"))
    if _QUESTION.search(url):
        raise LinkParseError.unsupported_platform("知乎问题")
    raise LinkParseError.unsupported_platform("知乎")


async def _fetch_initial_data(page_url: str) -> tuple[dict, str]:
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        raise LinkParseError.unsupported_platform("知乎(未安装 curl_cffi)") from None

    try:
        resp = await asyncio.to_thread(
            lambda: curl_requests.get(
                page_url, impersonate="chrome", timeout=20, allow_redirects=True
            )
        )
    except Exception as error:  # noqa: BLE001
        raise LinkParseError.network(str(error)) from error
    if resp.status_code not in (200,):
        if resp.status_code in (403, 418):
            raise LinkParseError.needs_auth()
        raise LinkParseError.parse_failed(f"知乎页面 HTTP {resp.status_code}")
    html = str(resp.text)
    matched = _INITIAL_SCRIPT.search(html)
    if not matched:
        if "zse-ck" in html or "challenge" in html.lower():
            raise LinkParseError.needs_auth()
        raise LinkParseError.parse_failed("知乎页面无反爬数据")
    try:
        return json.loads(matched.group(1).strip()), str(resp.url)
    except json.JSONDecodeError:
        raise LinkParseError.parse_failed("知乎 initialData 解析失败") from None


def _answer_entity(initial: dict, aid: str) -> dict | None:
    entities = (initial.get("initialState") or {}).get("entities") or {}
    answer = (entities.get("answers") or {}).get(aid)
    return answer if isinstance(answer, dict) else None


async def _parse_answer_answer(original: str, qid: str, aid: str) -> ParsedLink:
    page_url = f"https://www.zhihu.com/question/{qid}/answer/{aid}"
    initial, _final = await _fetch_initial_data(page_url)
    answer = _answer_entity(initial, aid)
    if not answer:
        raise LinkParseError.parse_failed("知乎回答正文不存在")
    content = strip_html(answer.get("content") or "")
    if not content:
        raise LinkParseError.parse_failed("知乎回答无正文")
    author = ""
    user = answer.get("author") or {}
    if isinstance(user, dict):
        author = user.get("name") or ""
    title = _answer_title(initial, qid, aid, content)
    desc = f"{title}\n{content}" if title and not content.startswith(title) else content
    return ParsedLink(platform="zhihu", title=title, desc=desc, author=author, url=original)


def _answer_title(initial: dict, qid: str, aid: str, content: str) -> str:
    entities = (initial.get("initialState") or {}).get("entities") or {}
    question = (entities.get("questions") or {}).get(qid)
    if isinstance(question, dict) and question.get("title"):
        return str(question["title"]).strip()
    first_line = content.splitlines()[0].strip() if content else ""
    return first_line[:80]


async def _parse_article(original: str, article_id: str) -> ParsedLink:
    page_url = f"https://zhuanlan.zhihu.com/p/{article_id}"
    initial, _final = await _fetch_initial_data(page_url)
    entities = (initial.get("initialState") or {}).get("entities") or {}
    article = (entities.get("articles") or {}).get(article_id)
    if not isinstance(article, dict):
        raise LinkParseError.parse_failed("知乎专栏正文不存在")
    title = (article.get("title") or "").strip()
    content = strip_html(article.get("content") or "")
    if not content:
        raise LinkParseError.parse_failed("知乎专栏无正文")
    author = ""
    user = article.get("author") or {}
    if isinstance(user, dict):
        author = user.get("name") or ""
    desc = f"{title}\n{content}" if title and not content.startswith(title) else content
    return ParsedLink(platform="zhihu", title=title, desc=desc, author=author, url=original)