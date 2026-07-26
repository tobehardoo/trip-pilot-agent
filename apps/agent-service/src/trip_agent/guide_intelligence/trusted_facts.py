"""Typed normalization, validation, and conflict handling for travel facts."""

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from email.message import Message
from typing import Literal

from bs4 import BeautifulSoup, Tag

type ReliabilityLevel = Literal[
    "OFFICIAL_ATTRACTION",
    "OFFICIAL_TOURISM",
    "WEATHER_PROVIDER",
    "MAP_PROVIDER",
    "PUBLIC_GUIDE",
    "COMMUNITY",
]
type TrustedFactCategory = Literal[
    "ADDRESS",
    "COORDINATES",
    "OPENING_HOURS",
    "TEMPORARY_CLOSURE",
    "TICKET_PRICE",
    "REFERENCE_SPEND",
    "RESERVATION_REQUIREMENT",
    "RESERVATION_ENTRY",
    "TRANSPORT_ADVICE",
    "WEATHER",
    "VENUE_ENVIRONMENT",
    "ATTRACTION_IDENTITY",
]

_FACT_CATEGORIES = frozenset(
    {
        "ADDRESS",
        "COORDINATES",
        "OPENING_HOURS",
        "TEMPORARY_CLOSURE",
        "TICKET_PRICE",
        "REFERENCE_SPEND",
        "RESERVATION_REQUIREMENT",
        "RESERVATION_ENTRY",
        "TRANSPORT_ADVICE",
        "WEATHER",
        "VENUE_ENVIRONMENT",
        "ATTRACTION_IDENTITY",
    }
)
_OFFICIAL_RELIABILITY = frozenset({"OFFICIAL_ATTRACTION", "OFFICIAL_TOURISM"})
_OFFICIAL_SOURCE_TYPES = frozenset(
    {"OFFICIAL_ATTRACTION_HTML", "OFFICIAL_TOURISM_HTML"}
)
_STRONG_FACTS = frozenset(
    {
        "OPENING_HOURS",
        "TEMPORARY_CLOSURE",
        "TICKET_PRICE",
        "RESERVATION_REQUIREMENT",
    }
)
_HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_HTML_CONTENT_SELECTORS = ("article", "main", "[role='main']", ".article", ".content")
_REMOVED_HTML_SELECTORS = (
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "header",
    "form",
    "aside",
)
_BLOCK_TAGS = ("p", "li", "h1", "h2", "h3", "blockquote")
_WHITESPACE = re.compile(r"[^\S\r\n]+")
_MULTIPLE_LINES = re.compile(r"\n{2,}")
_MARKDOWN_PREFIX = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+|>\s*)")
_XHS_BOILERPLATE = re.compile(r"复制后打开【?小红书】?.*(?:查看|笔记|内容)")
_XHS_LINK = re.compile(r"^https?://(?:www\.)?xhslink\.com/\S+$", re.I)
_CJK = re.compile(r"[\u3400-\u9fff]")
_TIME = re.compile(r"(?P<open>\d{1,2}:\d{2})\s*[-—至到]\s*(?P<close>\d{1,2}:\d{2})")
_PRICE = re.compile(
    r"(?P<label>成人门票|儿童票|学生票|官方门票|门票|票价)"
    r"\s*(?:为|约|参考|[:：])?\s*(?P<amount>\d+(?:\.\d+)?)\s*元"
)
_REFERENCE_SPEND = re.compile(
    r"(?P<label>人均|参考消费)\s*(?:约|[:：])?\s*(?P<amount>\d+(?:\.\d+)?)\s*元"
)
_ADDRESS = re.compile(r"(?:地址|位于)\s*[:：]?\s*(?P<address>[^。\n]{4,200})")
_COORDINATES = re.compile(
    r"(?:坐标|经纬度)\s*[:：]?\s*(?P<longitude>-?\d{1,3}(?:\.\d+)?)"
    r"\s*[,，]\s*(?P<latitude>-?\d{1,2}(?:\.\d+)?)"
)
_DATE = re.compile(r"(?P<date>20\d{2})[-年/](?P<month>\d{1,2})[-月/](?P<day>\d{1,2})日?")
_TTL_BY_CATEGORY: dict[str, timedelta] = {
    "ADDRESS": timedelta(days=90),
    "COORDINATES": timedelta(days=90),
    "OPENING_HOURS": timedelta(days=14),
    "TEMPORARY_CLOSURE": timedelta(hours=6),
    "TICKET_PRICE": timedelta(days=14),
    "REFERENCE_SPEND": timedelta(days=14),
    "RESERVATION_REQUIREMENT": timedelta(days=7),
    "RESERVATION_ENTRY": timedelta(days=7),
    "TRANSPORT_ADVICE": timedelta(days=14),
    "WEATHER": timedelta(hours=6),
    "VENUE_ENVIRONMENT": timedelta(days=90),
    "ATTRACTION_IDENTITY": timedelta(days=90),
}


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    document_id: str
    source_type: str
    source_name: str
    source_url: str | None
    city: str
    title: str
    content: str
    fetched_at: datetime
    content_hash: str
    encoding: str
    language: str
    metadata: Mapping[str, object]
    reliability_level: ReliabilityLevel
    source_reviewed: bool = False


@dataclass(frozen=True, slots=True)
class CandidateFact:
    category: str
    statement: str
    normalized_value: Mapping[str, object]
    evidence: str
    evidence_start: int
    evidence_end: int
    confidence: float
    checked_at: datetime
    expires_at: datetime
    effective_date: date | None = None


@dataclass(frozen=True, slots=True)
class ValidationReason:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class RejectedFact:
    candidate: CandidateFact
    reasons: tuple[ValidationReason, ...]


@dataclass(frozen=True, slots=True)
class ValidatedFact:
    fact_id: str
    document_id: str
    category: str
    statement: str
    normalized_value: Mapping[str, object]
    evidence: str
    evidence_start: int
    evidence_end: int
    confidence: float
    checked_at: datetime
    expires_at: datetime
    effective_date: date | None
    source_type: str
    source_name: str
    source_url: str | None
    reliability_level: str
    source_reviewed: bool
    hard_constraint_eligible: bool


@dataclass(frozen=True, slots=True)
class FactValidationResult:
    accepted: tuple[ValidatedFact, ...]
    rejected: tuple[RejectedFact, ...]


@dataclass(frozen=True, slots=True)
class FactMergeDecision:
    selected_fact: ValidatedFact
    conflict_facts: tuple[ValidatedFact, ...]
    downgraded_facts: tuple[ValidatedFact, ...]
    reason: str
    needs_manual_review: bool


@dataclass(frozen=True, slots=True)
class FactMergeResult:
    selected_facts: tuple[ValidatedFact, ...]
    decisions: tuple[FactMergeDecision, ...]


class DocumentNormalizer:
    """Normalize supported user and official inputs without performing network access."""

    def __init__(self, *, max_content_characters: int = 100_000) -> None:
        if max_content_characters < 1:
            raise ValueError("max_content_characters must be positive")
        self._max_content_characters = max_content_characters

    def normalize_text(
        self,
        *,
        source_type: str,
        source_name: str,
        source_url: str | None,
        city: str,
        title: str,
        content: str,
        fetched_at: datetime,
        encoding: str,
        reliability_level: ReliabilityLevel,
        source_reviewed: bool = False,
        metadata: Mapping[str, object] | None = None,
    ) -> NormalizedDocument:
        _require_aware(fetched_at, "fetched_at")
        normalized = _normalize_text_content(content, source_type)
        return self._build(
            source_type=source_type,
            source_name=source_name,
            source_url=source_url,
            city=city,
            title=title,
            content=normalized,
            fetched_at=fetched_at,
            encoding=encoding,
            reliability_level=reliability_level,
            source_reviewed=source_reviewed,
            metadata=metadata,
        )

    def normalize_html(
        self,
        *,
        source_type: str,
        source_name: str,
        source_url: str,
        city: str,
        content: bytes,
        content_type: str | None,
        fetched_at: datetime,
        reliability_level: ReliabilityLevel,
        source_reviewed: bool = False,
        metadata: Mapping[str, object] | None = None,
    ) -> NormalizedDocument:
        _require_aware(fetched_at, "fetched_at")
        media_type, charset = _parse_content_type(content_type)
        if media_type not in _HTML_CONTENT_TYPES:
            raise ValueError(f"unsupported HTML content type: {content_type or 'missing'}")
        soup = BeautifulSoup(content, "html.parser", from_encoding=charset)
        container = _select_html_container(soup)
        for selector in _REMOVED_HTML_SELECTORS:
            for node in container.select(selector):
                node.decompose()
        blocks = [
            _normalize_line(node.get_text(" ", strip=True))
            for node in container.find_all(_BLOCK_TAGS)
        ]
        normalized = "\n".join(block for block in blocks if block)
        if not normalized:
            normalized = _normalize_line(container.get_text(" ", strip=True))
        title = _html_title(soup)
        return self._build(
            source_type=source_type,
            source_name=source_name,
            source_url=source_url,
            city=city,
            title=title,
            content=normalized,
            fetched_at=fetched_at,
            encoding=charset or soup.original_encoding or "unknown",
            reliability_level=reliability_level,
            source_reviewed=source_reviewed,
            metadata=metadata,
        )

    def normalize_structured(
        self,
        *,
        source_type: str,
        source_name: str,
        source_url: str,
        city: str,
        title: str,
        content: str,
        fetched_at: datetime,
        reliability_level: ReliabilityLevel,
        metadata: Mapping[str, object],
        source_reviewed: bool = True,
    ) -> NormalizedDocument:
        return self.normalize_text(
            source_type=source_type,
            source_name=source_name,
            source_url=source_url,
            city=city,
            title=title,
            content=content,
            fetched_at=fetched_at,
            encoding="structured-json",
            reliability_level=reliability_level,
            source_reviewed=source_reviewed,
            metadata=metadata,
        )

    def _build(
        self,
        *,
        source_type: str,
        source_name: str,
        source_url: str | None,
        city: str,
        title: str,
        content: str,
        fetched_at: datetime,
        encoding: str,
        reliability_level: ReliabilityLevel,
        source_reviewed: bool,
        metadata: Mapping[str, object] | None,
    ) -> NormalizedDocument:
        values = {
            "source_type": source_type,
            "source_name": source_name,
            "city": city,
            "title": title,
            "encoding": encoding,
        }
        normalized_values = {name: value.strip() for name, value in values.items()}
        if any(not value for value in normalized_values.values()):
            raise ValueError("normalized document fields cannot be empty")
        if not content.strip():
            raise ValueError("normalized document content cannot be empty")
        if len(content) > self._max_content_characters:
            raise ValueError("normalized document exceeds maximum content length")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        identity = hashlib.sha256(
            f"{source_type}\0{source_url or source_name}\0{content_hash}".encode()
        ).hexdigest()
        return NormalizedDocument(
            document_id=f"doc_{identity[:32]}",
            source_type=normalized_values["source_type"],
            source_name=normalized_values["source_name"],
            source_url=source_url,
            city=normalized_values["city"],
            title=normalized_values["title"][:300],
            content=content,
            fetched_at=fetched_at.astimezone(UTC),
            content_hash=content_hash,
            encoding=normalized_values["encoding"],
            language="zh-CN" if _CJK.search(content) else "und",
            metadata=dict(metadata or {}),
            reliability_level=reliability_level,
            source_reviewed=source_reviewed,
        )


class RuleFactExtractor:
    """Deterministically extract evidence-backed candidates from normalized text."""

    def extract(
        self,
        document: NormalizedDocument,
        *,
        checked_at: datetime,
    ) -> tuple[CandidateFact, ...]:
        _require_aware(checked_at, "checked_at")
        candidates: list[CandidateFact] = []
        cursor = 0
        for sentence in _sentences(document.content):
            start = document.content.find(sentence, cursor)
            if start < 0:
                start = document.content.find(sentence)
            cursor = max(cursor, start + len(sentence))
            effective_date = _effective_date(sentence)
            matches: list[tuple[str, Mapping[str, object], float]] = []
            if address := _ADDRESS.search(sentence):
                matches.append(
                    ("ADDRESS", {"address": address.group("address").strip()}, 0.9)
                )
            if coordinates := _COORDINATES.search(sentence):
                matches.append(
                    (
                        "COORDINATES",
                        {
                            "longitude": float(coordinates.group("longitude")),
                            "latitude": float(coordinates.group("latitude")),
                        },
                        0.95,
                    )
                )
            if opening := _TIME.search(sentence):
                matches.append(
                    (
                        "OPENING_HOURS",
                        {
                            "openTime": opening.group("open"),
                            "closeTime": opening.group("close"),
                        },
                        0.9,
                    )
                )
            if re.search(r"临时关闭|临时闭馆|暂停开放|闭园", sentence):
                matches.append(("TEMPORARY_CLOSURE", {"closed": True}, 0.94))
            if price := _PRICE.search(sentence):
                matches.append(
                    (
                        "TICKET_PRICE",
                        {"amount": float(price.group("amount")), "currency": "CNY"},
                        0.9,
                    )
                )
            if spend := _REFERENCE_SPEND.search(sentence):
                matches.append(
                    (
                        "REFERENCE_SPEND",
                        {"amount": float(spend.group("amount")), "currency": "CNY"},
                        0.82,
                    )
                )
            if re.search(r"需要(?:提前)?预约|必须预约|预约参观|实名预约", sentence):
                matches.append(("RESERVATION_REQUIREMENT", {"required": True}, 0.9))
            elif re.search(r"无需预约|免预约", sentence):
                matches.append(("RESERVATION_REQUIREMENT", {"required": False}, 0.84))
            if re.search(r"预约入口|预约渠道|微信公众号.*预约|小程序.*预约", sentence):
                matches.append(("RESERVATION_ENTRY", {"entryHint": sentence}, 0.84))
            if re.search(r"地铁|公交|步行|打车|交通", sentence):
                matches.append(("TRANSPORT_ADVICE", {"advice": sentence}, 0.82))
            if re.search(r"天气|降雨|下雨|雷阵雨|晴|多云|气温|温度|台风", sentence):
                matches.append(
                    (
                        "WEATHER",
                        {"condition": _weather_condition(sentence)},
                        0.86,
                    )
                )
            if re.search(r"室内|室外|露天|户外", sentence):
                environment = "INDOOR" if "室内" in sentence else "OUTDOOR"
                matches.append(("VENUE_ENVIRONMENT", {"environment": environment}, 0.86))
            for category, normalized_value, confidence in matches:
                candidates.append(
                    CandidateFact(
                        category=category,
                        statement=sentence,
                        normalized_value=normalized_value,
                        evidence=sentence,
                        evidence_start=start,
                        evidence_end=start + len(sentence),
                        confidence=confidence,
                        checked_at=checked_at.astimezone(UTC),
                        expires_at=checked_at.astimezone(UTC) + _TTL_BY_CATEGORY[category],
                        effective_date=effective_date,
                    )
                )
        return tuple(candidates)


class FactValidator:
    """Validate candidate facts independently of extractors and persistence."""

    def validate(
        self,
        document: NormalizedDocument,
        candidates: Iterable[CandidateFact],
        *,
        trip_start: date | None = None,
        trip_end: date | None = None,
    ) -> FactValidationResult:
        accepted: list[ValidatedFact] = []
        rejected: list[RejectedFact] = []
        for candidate in candidates:
            reasons = self._reasons(
                document,
                candidate,
                trip_start=trip_start,
                trip_end=trip_end,
            )
            if reasons:
                rejected.append(RejectedFact(candidate=candidate, reasons=tuple(reasons)))
                continue
            hard_eligible = (
                candidate.category in _STRONG_FACTS
                and document.reliability_level in _OFFICIAL_RELIABILITY
                and document.source_reviewed
                and candidate.expires_at > candidate.checked_at
            )
            fact_hash = hashlib.sha256(
                (
                    f"{document.document_id}\0{candidate.category}\0"
                    f"{candidate.statement}\0{candidate.effective_date or ''}"
                ).encode()
            ).hexdigest()
            accepted.append(
                ValidatedFact(
                    fact_id=f"fact_{fact_hash[:32]}",
                    document_id=document.document_id,
                    category=candidate.category,
                    statement=candidate.statement.strip(),
                    normalized_value=dict(candidate.normalized_value),
                    evidence=candidate.evidence,
                    evidence_start=candidate.evidence_start,
                    evidence_end=candidate.evidence_end,
                    confidence=candidate.confidence,
                    checked_at=candidate.checked_at.astimezone(UTC),
                    expires_at=candidate.expires_at.astimezone(UTC),
                    effective_date=candidate.effective_date,
                    source_type=document.source_type,
                    source_name=document.source_name,
                    source_url=document.source_url,
                    reliability_level=document.reliability_level,
                    source_reviewed=document.source_reviewed,
                    hard_constraint_eligible=hard_eligible,
                )
            )
        return FactValidationResult(accepted=tuple(accepted), rejected=tuple(rejected))

    def _reasons(
        self,
        document: NormalizedDocument,
        candidate: CandidateFact,
        *,
        trip_start: date | None,
        trip_end: date | None,
    ) -> list[ValidationReason]:
        reasons: list[ValidationReason] = []
        if candidate.category not in _FACT_CATEGORIES:
            reasons.append(_reason("CATEGORY_INVALID", "fact category is unsupported"))
        if not candidate.statement.strip():
            reasons.append(_reason("STATEMENT_EMPTY", "fact statement cannot be empty"))
        if len(candidate.statement) > 2_000 or len(candidate.evidence) > 2_000:
            reasons.append(_reason("TEXT_TOO_LONG", "fact statement or evidence is too long"))
        span_valid = (
            0 <= candidate.evidence_start < candidate.evidence_end <= len(document.content)
        )
        if not span_valid:
            reasons.append(_reason("EVIDENCE_SPAN_INVALID", "evidence span is out of bounds"))
        else:
            spanned = document.content[
                candidate.evidence_start : candidate.evidence_end
            ]
            if spanned != candidate.evidence:
                reasons.append(
                    _reason("EVIDENCE_SPAN_INVALID", "evidence span does not match evidence")
                )
        if candidate.evidence not in document.content:
            reasons.append(_reason("EVIDENCE_MISMATCH", "evidence is absent from document"))
        if not 0 <= candidate.confidence <= 1:
            reasons.append(_reason("CONFIDENCE_INVALID", "confidence is outside zero to one"))
        if (
            candidate.checked_at.tzinfo is None
            or candidate.expires_at.tzinfo is None
            or candidate.expires_at <= candidate.checked_at
        ):
            reasons.append(_reason("EXPIRY_INVALID", "expiry must be after checked time"))
        if candidate.category == "OPENING_HOURS":
            self._validate_opening(candidate, reasons)
        if candidate.category in {"TICKET_PRICE", "REFERENCE_SPEND"}:
            self._validate_amount(candidate, reasons)
        if candidate.category == "COORDINATES":
            self._validate_coordinates(candidate, reasons)
        if (
            candidate.effective_date is not None
            and trip_start is not None
            and trip_end is not None
            and not trip_start <= candidate.effective_date <= trip_end
        ):
            reasons.append(
                _reason(
                    "EFFECTIVE_DATE_OUTSIDE_TRIP",
                    "fact effective date is outside the requested trip",
                )
            )
        official_reliability = document.reliability_level in _OFFICIAL_RELIABILITY
        if official_reliability and document.source_type not in _OFFICIAL_SOURCE_TYPES:
            reasons.append(
                _reason(
                    "SOURCE_RELIABILITY_MISMATCH",
                    "non-official source cannot use official reliability",
                )
            )
        if official_reliability and not document.source_reviewed:
            reasons.append(
                _reason(
                    "OFFICIAL_SOURCE_UNREVIEWED",
                    "official facts require an approved source registry entry",
                )
            )
        if candidate.category in _STRONG_FACTS and len(candidate.evidence.strip()) < 6:
            reasons.append(
                _reason(
                    "STRONG_FACT_EVIDENCE_INSUFFICIENT",
                    "strong fact evidence is too short",
                )
            )
        return reasons

    def _validate_opening(
        self,
        candidate: CandidateFact,
        reasons: list[ValidationReason],
    ) -> None:
        try:
            open_at = time.fromisoformat(str(candidate.normalized_value["openTime"]))
            close_at = time.fromisoformat(str(candidate.normalized_value["closeTime"]))
            if close_at <= open_at:
                reasons.append(
                    _reason(
                        "OPENING_HOURS_REVERSED",
                        "closing time cannot precede opening time",
                    )
                )
        except (KeyError, TypeError, ValueError):
            reasons.append(
                _reason("OPENING_HOURS_INVALID", "opening hours must use HH:MM values")
            )

    def _validate_amount(
        self,
        candidate: CandidateFact,
        reasons: list[ValidationReason],
    ) -> None:
        amount = candidate.normalized_value.get("amount")
        currency = candidate.normalized_value.get("currency")
        if (
            not isinstance(amount, int | float)
            or isinstance(amount, bool)
            or amount < 0
            or currency not in {"CNY"}
        ):
            reasons.append(
                _reason(
                    "AMOUNT_INVALID",
                    "amount must be non-negative and have an explicit supported currency",
                )
            )

    def _validate_coordinates(
        self,
        candidate: CandidateFact,
        reasons: list[ValidationReason],
    ) -> None:
        longitude = candidate.normalized_value.get("longitude")
        latitude = candidate.normalized_value.get("latitude")
        if (
            not isinstance(longitude, int | float)
            or isinstance(longitude, bool)
            or not isinstance(latitude, int | float)
            or isinstance(latitude, bool)
            or not -180 <= longitude <= 180
            or not -90 <= latitude <= 90
        ):
            reasons.append(
                _reason("COORDINATES_INVALID", "coordinates are outside valid ranges")
            )


class FactMerger:
    """Merge facts with category-aware source precedence and explicit decisions."""

    def __init__(self, *, aliases: Mapping[str, str] | None = None) -> None:
        self._aliases = {
            key.casefold().strip(): value.casefold().strip()
            for key, value in (aliases or {}).items()
        }

    def merge(self, facts: Iterable[ValidatedFact]) -> FactMergeResult:
        groups: dict[tuple[str, str, date | None], list[ValidatedFact]] = {}
        for fact in facts:
            entity = self._entity(fact)
            groups.setdefault((fact.category, entity, fact.effective_date), []).append(fact)
        decisions: list[FactMergeDecision] = []
        for group in groups.values():
            ranked = sorted(group, key=self._rank, reverse=True)
            selected = ranked[0]
            conflicts = tuple(
                fact
                for fact in ranked
                if fact.normalized_value != selected.normalized_value
            )
            downgraded = tuple(fact for fact in ranked[1:])
            same_rank_conflict = bool(
                conflicts
                and len(ranked) > 1
                and self._rank_tier(ranked[0]) == self._rank_tier(ranked[1])
            )
            decisions.append(
                FactMergeDecision(
                    selected_fact=selected,
                    conflict_facts=conflicts,
                    downgraded_facts=downgraded,
                    reason=self._reason(selected, bool(conflicts)),
                    needs_manual_review=same_rank_conflict,
                )
            )
        decisions.sort(key=lambda item: item.selected_fact.fact_id)
        return FactMergeResult(
            selected_facts=tuple(decision.selected_fact for decision in decisions),
            decisions=tuple(decisions),
        )

    def _entity(self, fact: ValidatedFact) -> str:
        raw_name = fact.normalized_value.get("poiName")
        if not isinstance(raw_name, str) or not raw_name.strip():
            return fact.fact_id
        normalized = raw_name.casefold().strip()
        return self._aliases.get(normalized, normalized)

    def _rank(self, fact: ValidatedFact) -> tuple[int, int, float, datetime]:
        return (
            self._rank_tier(fact),
            1 if fact.expires_at > fact.checked_at else 0,
            fact.confidence,
            fact.checked_at,
        )

    def _rank_tier(self, fact: ValidatedFact) -> int:
        reliability_rank = {
            "OFFICIAL_ATTRACTION": 70,
            "OFFICIAL_TOURISM": 60,
            "WEATHER_PROVIDER": 50,
            "MAP_PROVIDER": 40,
            "PUBLIC_GUIDE": 30,
            "COMMUNITY": 20,
        }.get(fact.reliability_level, 0)
        if fact.source_reviewed and fact.reliability_level in _OFFICIAL_RELIABILITY:
            reliability_rank += 10
        return reliability_rank

    def _reason(self, fact: ValidatedFact, has_conflict: bool) -> str:
        prefix = (
            "selected reviewed official source"
            if fact.source_reviewed and fact.reliability_level in _OFFICIAL_RELIABILITY
            else f"selected {fact.reliability_level.casefold()} source"
        )
        if has_conflict:
            return f"{prefix}; conflict resolved by reliability, freshness, and evidence"
        return prefix


def fact_ttl(category: str) -> timedelta:
    """Return the centralized TTL for a trusted fact category."""

    try:
        return _TTL_BY_CATEGORY[category]
    except KeyError as error:
        raise ValueError(f"unsupported fact category: {category}") from error


def _select_html_container(soup: BeautifulSoup) -> Tag:
    for selector in _HTML_CONTENT_SELECTORS:
        candidates = [node for node in soup.select(selector) if isinstance(node, Tag)]
        if candidates:
            return max(candidates, key=lambda node: len(node.get_text(" ", strip=True)))
    if soup.body is not None:
        return soup.body
    return soup


def _html_title(soup: BeautifulSoup) -> str:
    heading = soup.find("h1")
    if heading is not None:
        title = _normalize_line(heading.get_text(" ", strip=True))
        if title:
            return title
    if soup.title is not None:
        title = _normalize_line(soup.title.get_text(" ", strip=True))
        if title:
            return title
    return "未命名城市情报"


def _normalize_text_content(content: str, source_type: str) -> str:
    if not isinstance(content, str):
        raise ValueError("document content must be text")
    blocks: list[str] = []
    for raw_line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _normalize_line(_MARKDOWN_PREFIX.sub("", raw_line))
        if not line:
            continue
        if source_type == "XIAOHONGSHU_SHARED_TEXT" and (
            _XHS_BOILERPLATE.search(line) or _XHS_LINK.fullmatch(line)
        ):
            continue
        blocks.append(line)
    return _MULTIPLE_LINES.sub("\n", "\n".join(blocks)).strip()


def _normalize_line(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def _sentences(content: str) -> Iterable[str]:
    for line in content.splitlines():
        normalized = line.strip()
        if normalized:
            yield normalized


def _effective_date(sentence: str) -> date | None:
    match = _DATE.search(sentence)
    if match is None:
        return None
    try:
        return date(
            int(match.group("date")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError:
        return None


def _weather_condition(sentence: str) -> str:
    if re.search(r"雷阵雨|降雨|下雨|雨", sentence):
        return "RAIN"
    if "晴" in sentence:
        return "CLEAR"
    if "多云" in sentence:
        return "CLOUDY"
    if "台风" in sentence:
        return "TYPHOON"
    return "UNKNOWN"


def _parse_content_type(value: str | None) -> tuple[str, str | None]:
    if value is None or not value.strip():
        return "", None
    message = Message()
    message["content-type"] = value
    return message.get_content_type().casefold(), message.get_content_charset()


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _reason(code: str, message: str) -> ValidationReason:
    return ValidationReason(code=code, message=message)
