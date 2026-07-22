"""Structured HTML extraction and quality checks for Guangzhou government pages."""

import re
from codecs import lookup as lookup_codec
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import Message
from typing import Literal
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

type QualitySeverity = Literal["WARNING", "ERROR"]
type QualityIssueCode = Literal[
    "ARTICLE_CONTAINER_MISSING",
    "CONTENT_TOO_SHORT",
    "DYNAMIC_FACTS_PRESENT",
    "PUBLISHED_AT_IN_FUTURE",
    "PUBLISHED_AT_MISSING",
    "TITLE_MISSING",
    "UNSUPPORTED_CONTENT_ENCODING",
    "UNSUPPORTED_CONTENT_TYPE",
]

_PARSER_VERSION = "gz-government-bs4-v1"
_SUPPORTED_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_ARTICLE_SELECTORS = (
    "#zoomcon",
    ".content_article",
    ".TRS_Editor",
    "main",
    "article:not(.newgotop)",
)
_REMOVED_SELECTORS = (
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "form",
    "button",
    ".share",
    ".share-box",
    ".toolbar",
    ".related",
)
_BLOCK_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "figcaption"})
_TAIL_SENTINELS = ("相关附件", "相关新闻", "相关内容")
_DYNAMIC_FACT_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"(?:开放|营业|开馆)时间|闭馆|停止入场",
        r"(?:门票|票价|价格|收费|免费|免票|入场费)",
        r"(?:预约|购票|实名)",
        r"(?:公交|地铁)|交通(?:方式|指南|路线|线路|运营|时刻)",
    )
)
_WHITESPACE = re.compile(r"\s+")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class ExtractionQualityIssue:
    code: QualityIssueCode
    severity: QualitySeverity
    message: str


@dataclass(frozen=True, slots=True)
class ExtractedArticle:
    title: str
    content: str
    published_at: datetime | None
    content_source: str | None
    parser_version: str


@dataclass(frozen=True, slots=True)
class ArticleExtractionPassed:
    status: Literal["EXTRACTED"]
    article: ExtractedArticle
    issues: tuple[ExtractionQualityIssue, ...]


@dataclass(frozen=True, slots=True)
class ArticleExtractionRejected:
    status: Literal["REJECTED"]
    parser_version: str
    issues: tuple[ExtractionQualityIssue, ...]


type ArticleExtractionResult = ArticleExtractionPassed | ArticleExtractionRejected


class GuangzhouGovernmentArticleExtractor:
    parser_version = _PARSER_VERSION

    def __init__(
        self,
        *,
        min_content_characters: int = 60,
        future_tolerance: timedelta = timedelta(minutes=5),
    ) -> None:
        if (
            not isinstance(min_content_characters, int)
            or isinstance(min_content_characters, bool)
            or min_content_characters < 1
        ):
            raise ValueError("min_content_characters must be positive")
        if future_tolerance < timedelta(0):
            raise ValueError("future_tolerance cannot be negative")
        self._min_content_characters = min_content_characters
        self._future_tolerance = future_tolerance

    def extract(
        self,
        *,
        content: bytes,
        content_type: str | None,
        fetched_at: datetime,
    ) -> ArticleExtractionResult:
        fetched = _as_utc(fetched_at, "fetched_at")
        media_type, charset = _parse_content_type(content_type)
        if media_type not in _SUPPORTED_CONTENT_TYPES:
            return _rejected(
                "UNSUPPORTED_CONTENT_TYPE",
                f"unsupported article content type: {content_type or 'missing'}",
            )
        if charset is not None:
            try:
                lookup_codec(charset)
            except LookupError:
                return _rejected(
                    "UNSUPPORTED_CONTENT_ENCODING",
                    f"unsupported article character encoding: {charset}",
                )

        soup = BeautifulSoup(content, "html.parser", from_encoding=charset)
        container = _select_article_container(soup)
        if container is None:
            return _rejected(
                "ARTICLE_CONTAINER_MISSING",
                "official article body container was not found",
            )
        article_content = _extract_content(container)
        if len(article_content) < self._min_content_characters:
            return _rejected(
                "CONTENT_TOO_SHORT",
                "extracted article content is below the quality threshold",
            )

        title = _extract_title(soup)
        if title is None:
            return _rejected("TITLE_MISSING", "official article title was not found")

        published_at = _extract_published_at(soup)
        if published_at is not None and published_at > fetched + self._future_tolerance:
            return _rejected(
                "PUBLISHED_AT_IN_FUTURE",
                "article publication time is later than the fetch time",
            )

        issues: list[ExtractionQualityIssue] = []
        if published_at is None:
            issues.append(
                ExtractionQualityIssue(
                    code="PUBLISHED_AT_MISSING",
                    severity="WARNING",
                    message="official publication time was not available",
                )
            )
        if any(pattern.search(article_content) for pattern in _DYNAMIC_FACT_PATTERNS):
            issues.append(
                ExtractionQualityIssue(
                    code="DYNAMIC_FACTS_PRESENT",
                    severity="WARNING",
                    message="article contains facts that require real-time verification",
                )
            )

        return ArticleExtractionPassed(
            status="EXTRACTED",
            article=ExtractedArticle(
                title=title,
                content=article_content,
                published_at=published_at,
                content_source=_meta_content(soup, "contentsource"),
                parser_version=self.parser_version,
            ),
            issues=tuple(issues),
        )


def _select_article_container(soup: BeautifulSoup) -> Tag | None:
    for selector in _ARTICLE_SELECTORS:
        candidates = [node for node in soup.select(selector) if isinstance(node, Tag)]
        if candidates:
            return max(candidates, key=lambda node: len(node.get_text("", strip=True)))
    return None


def _extract_content(container: Tag) -> str:
    for selector in _REMOVED_SELECTORS:
        for node in container.select(selector):
            node.decompose()

    blocks: list[str] = []
    previous: str | None = None
    for node in container.find_all(_BLOCK_TAGS):
        if node.name == "li" and node.find(_BLOCK_TAGS):
            continue
        text = _normalize_text(node.get_text(" ", strip=True))
        if not text:
            continue
        if _is_tail_sentinel(text):
            break
        if text == previous:
            continue
        blocks.append(text)
        previous = text

    if not blocks:
        fallback_blocks: list[str] = []
        previous_fallback: str | None = None
        for value in container.stripped_strings:
            text = _normalize_text(str(value))
            if _is_tail_sentinel(text):
                break
            if text and text != previous_fallback:
                fallback_blocks.append(text)
                previous_fallback = text
        return "\n\n".join(fallback_blocks)
    return "\n\n".join(blocks)


def _extract_title(soup: BeautifulSoup) -> str | None:
    metadata_title = _meta_content(soup, "articletitle")
    if metadata_title:
        return metadata_title
    heading = soup.select_one("h1")
    if heading is not None:
        title = _normalize_text(heading.get_text(" ", strip=True))
        if title:
            return title
    if soup.title is not None:
        title = _normalize_text(soup.title.get_text(" ", strip=True))
        suffix = " - 广州市人民政府门户网站"
        if title.endswith(suffix):
            title = title.removesuffix(suffix).strip()
        return title or None
    return None


def _extract_published_at(soup: BeautifulSoup) -> datetime | None:
    raw_value = _meta_content(soup, "pubdate")
    if raw_value is None:
        time_node = soup.find("time", attrs={"datetime": True})
        raw_value = time_node.get("datetime") if time_node is not None else None
    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    value = raw_value.strip().replace("Z", "+00:00")
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        for format_string in ("%Y年%m月%d日 %H:%M:%S", "%Y年%m月%d日"):
            try:
                parsed = datetime.strptime(value, format_string)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI)
    return parsed.astimezone(UTC)


def _meta_content(soup: BeautifulSoup, expected_name: str) -> str | None:
    for node in soup.find_all("meta"):
        name = node.get("name") or node.get("property") or node.get("itemprop")
        if isinstance(name, str) and name.casefold() == expected_name:
            content = node.get("content")
            if isinstance(content, str):
                normalized = _normalize_text(content)
                return normalized or None
    return None


def _normalize_text(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def _is_tail_sentinel(value: str) -> bool:
    return value.rstrip(":：").strip() in _TAIL_SENTINELS


def _parse_content_type(value: str | None) -> tuple[str, str | None]:
    if value is None or not value.strip():
        return "", None
    message = Message()
    message["content-type"] = value
    return message.get_content_type().casefold(), message.get_content_charset()


def _rejected(code: QualityIssueCode, message: str) -> ArticleExtractionRejected:
    return ArticleExtractionRejected(
        status="REJECTED",
        parser_version=_PARSER_VERSION,
        issues=(ExtractionQualityIssue(code=code, severity="ERROR", message=message),),
    )


def _as_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)
