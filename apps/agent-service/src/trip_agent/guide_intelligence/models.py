"""Immutable models for imported guide intelligence."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from trip_agent.guide_intelligence.structured_model import ModelExtractionResult
from trip_agent.guide_intelligence.trusted_facts import (
    FactMergeDecision,
    NormalizedDocument,
    RejectedFact,
    ValidatedFact,
)

type GuideSourceType = Literal[
    "PUBLIC_GUIDE_URL",
    "PASTED_TEXT",
    "TEXT_FILE",
    "XIAOHONGSHU_SHARED_TEXT",
    "CITY_INTELLIGENCE",
    "OFFICIAL_TOURISM",
    "OFFICIAL_ATTRACTION",
]

type FactCategory = Literal[
    "ATTRACTION",
    "DINING",
    "TRANSPORT",
    "TIMING",
    "COST",
    "QUEUE",
    "RESERVATION",
    "LOCATION",
    "WEATHER",
    "TIP",
]


@dataclass(frozen=True, slots=True)
class TravelFact:
    category: FactCategory
    statement: str
    evidence: str
    confidence: float
    observed_at: datetime
    expires_at: datetime
    effective_date: date | None = None
    # Structured payload for opening-hours facts (scope/openingWindows/
    # effectiveDate/weekdayRules/raw).  Optional; other categories keep None.
    normalized_value: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.statement.strip() or not self.evidence.strip():
            raise ValueError("travel fact text cannot be empty")
        if not 0 <= self.confidence <= 1:
            raise ValueError("travel fact confidence must be between zero and one")
        for field_name, value in (
            ("observed_at", self.observed_at),
            ("expires_at", self.expires_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.expires_at <= self.observed_at:
            raise ValueError("travel fact expiry must be after observation")


@dataclass(frozen=True, slots=True)
class ExtractedGuide:
    title: str
    content: str
    facts: tuple[TravelFact, ...]
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class GuideImportResult:
    source_type: GuideSourceType
    source_url: str
    final_url: str
    source_host: str
    title: str
    excerpt: str
    content_hash: str
    fetched_at: datetime
    facts: tuple[TravelFact, ...]
    normalized_document: NormalizedDocument | None = None
    trusted_facts: tuple[ValidatedFact, ...] = ()
    rejected_facts: tuple[RejectedFact, ...] = ()
    merge_decisions: tuple[FactMergeDecision, ...] = ()
    model_extraction: ModelExtractionResult = field(
        default_factory=lambda: ModelExtractionResult(
            status="SKIPPED",
            candidates=(),
            attempts=0,
            failure_code="MODEL_NOT_RUN",
            failure_reason="trusted fact pipeline was not requested",
        )
    )
    quality: object | None = None  # GuideQualityScore | None, lazy import to avoid circular dep
