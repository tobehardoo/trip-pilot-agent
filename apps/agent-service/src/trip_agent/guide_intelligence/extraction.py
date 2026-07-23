"""Conservative, deterministic extraction for public travel articles."""

import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from email.message import Message

from bs4 import BeautifulSoup, Tag

from trip_agent.guide_intelligence.models import ExtractedGuide, FactCategory, TravelFact

_CONTENT_SELECTORS = ("article", "main", "[role='main']", ".article", ".content", ".post")
_REMOVED_SELECTORS = (
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "header",
    "form",
    "aside",
    ".advertisement",
    ".comments",
)
_BLOCK_TAGS = ("p", "li", "h2", "h3", "blockquote")
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*|\n+")
_WHITESPACE = re.compile(r"\s+")
_MAX_CONTENT_CHARACTERS = 100_000
_MAX_SENTENCE_CHARACTERS = 1_000
_MAX_SENTENCES = 500
_MAX_FACTS = 100
_CATEGORY_RULES: tuple[tuple[FactCategory, re.Pattern[str], int, float], ...] = (
    (
        "TRANSPORT",
        re.compile(r"地铁|公交|巴士|打车|步行|换乘|线路|号线|车站|metro|subway|bus|taxi", re.I),
        14,
        0.84,
    ),
    (
        "RESERVATION",
        re.compile(r"预约|预订|购票|抢票|实名|reservation|reserve|book(?:ing)?|ticket", re.I),
        7,
        0.86,
    ),
    (
        "QUEUE",
        re.compile(r"排队|等位|候场|拥挤|人流|queue|wait(?:ing)?", re.I),
        7,
        0.82,
    ),
    (
        "COST",
        re.compile(r"人均|门票|票价|免费|收费|预算|(?:\d+(?:\.\d+)?)\s*元|price|cost|free", re.I),
        14,
        0.82,
    ),
    (
        "TIMING",
        re.compile(r"开放时间|营业时间|闭馆|开门|关门|早上|上午|下午|晚上|\d{1,2}[:：]\d{2}", re.I),
        14,
        0.8,
    ),
    (
        "DINING",
        re.compile(
            r"餐厅|饭店|小吃|早茶|午饭|晚饭|肠粉|美食|咖啡|restaurant|food|lunch|dinner",
            re.I,
        ),
        30,
        0.78,
    ),
    (
        "ATTRACTION",
        re.compile(r"景点|博物馆|公园|寺|祠|塔|古镇|故居|展馆|值得|attraction|museum|park", re.I),
        90,
        0.76,
    ),
    (
        "TIP",
        re.compile(r"建议|注意|避雷|推荐|最好|记得|不要|tip|recommend|avoid", re.I),
        30,
        0.72,
    ),
)


class GenericGuideExtractor:
    """Extract readable article text and only explicitly supported travel facts."""

    def extract(
        self,
        *,
        content: bytes,
        content_type: str | None,
        fetched_at: datetime,
    ) -> ExtractedGuide:
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")
        media_type, charset = _parse_content_type(content_type)
        if media_type not in {"text/html", "application/xhtml+xml"}:
            raise ValueError(f"unsupported guide content type: {content_type or 'missing'}")

        soup = BeautifulSoup(content, "html.parser", from_encoding=charset)
        title = _extract_title(soup)
        container = _select_container(soup)
        for selector in _REMOVED_SELECTORS:
            for node in container.select(selector):
                node.decompose()
        sentences = _unique_sentences(_block_text(container))
        article_content = "\n".join(sentences)
        if not article_content:
            raise ValueError("guide page did not contain readable article text")
        return ExtractedGuide(
            title=title,
            content=article_content,
            facts=_extract_facts(sentences, fetched_at),
        )


def _select_container(soup: BeautifulSoup) -> Tag:
    for selector in _CONTENT_SELECTORS:
        candidates = [node for node in soup.select(selector) if isinstance(node, Tag)]
        if candidates:
            return max(candidates, key=lambda node: len(node.get_text(" ", strip=True)))
    if soup.body is not None:
        return soup.body
    return soup


def _extract_title(soup: BeautifulSoup) -> str:
    for attribute, value in (("property", "og:title"), ("name", "twitter:title")):
        node = soup.find("meta", attrs={attribute: value})
        if node is not None and isinstance(node.get("content"), str):
            title = _normalize(str(node["content"]))
            if title:
                return title[:300]
    heading = soup.find("h1")
    if heading is not None:
        title = _normalize(heading.get_text(" ", strip=True))
        if title:
            return title[:300]
    if soup.title is not None:
        title = _normalize(soup.title.get_text(" ", strip=True))
        if title:
            return title[:300]
    return "未命名旅行攻略"


def _block_text(container: Tag) -> Iterable[str]:
    blocks = container.find_all(_BLOCK_TAGS)
    if not blocks:
        blocks = [container]
    for block in blocks:
        text = _normalize(block.get_text(" ", strip=True))
        if not text:
            continue
        yield from (part for part in _SENTENCE_SPLIT.split(text) if part)


def _unique_sentences(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    content_characters = 0
    for value in values:
        sentence = _normalize(value)[:_MAX_SENTENCE_CHARACTERS]
        if not sentence or sentence in seen:
            continue
        separator_characters = 1 if result else 0
        remaining = _MAX_CONTENT_CHARACTERS - content_characters - separator_characters
        if remaining <= 0 or len(result) >= _MAX_SENTENCES:
            break
        sentence = sentence[:remaining]
        seen.add(sentence)
        result.append(sentence)
        content_characters += separator_characters + len(sentence)
    return tuple(result)


def _extract_facts(
    sentences: tuple[str, ...],
    fetched_at: datetime,
) -> tuple[TravelFact, ...]:
    facts: list[TravelFact] = []
    seen: set[tuple[FactCategory, str]] = set()
    for sentence in sentences:
        for category, pattern, ttl_days, confidence in _CATEGORY_RULES:
            identity = (category, sentence)
            if identity in seen or pattern.search(sentence) is None:
                continue
            seen.add(identity)
            facts.append(
                TravelFact(
                    category=category,
                    statement=sentence,
                    evidence=sentence,
                    confidence=confidence,
                    observed_at=fetched_at,
                    expires_at=fetched_at + timedelta(days=ttl_days),
                )
            )
            if len(facts) >= _MAX_FACTS:
                return tuple(facts)
    return tuple(facts)


def _parse_content_type(value: str | None) -> tuple[str, str | None]:
    if value is None or not value.strip():
        return "", None
    message = Message()
    message["content-type"] = value
    return message.get_content_type().casefold(), message.get_content_charset()


def _normalize(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()
