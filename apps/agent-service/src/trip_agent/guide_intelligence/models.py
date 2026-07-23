"""Immutable models for imported guide intelligence."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

type FactCategory = Literal[
    "ATTRACTION",
    "DINING",
    "TRANSPORT",
    "TIMING",
    "COST",
    "QUEUE",
    "RESERVATION",
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


@dataclass(frozen=True, slots=True)
class GuideImportResult:
    source_url: str
    final_url: str
    source_host: str
    title: str
    excerpt: str
    content_hash: str
    fetched_at: datetime
    facts: tuple[TravelFact, ...]
