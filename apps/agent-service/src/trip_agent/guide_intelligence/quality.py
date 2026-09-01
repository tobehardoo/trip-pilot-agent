"""Guide-level quality scoring.

Computes a 0–100 composite score from five dimensions after the full
import pipeline (extraction → validation → merging → model extraction)
has completed.  Pure functions — no side effects, no external calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trip_agent.guide_intelligence.models import GuideImportResult


# Weights must sum to 1.0.
_FACT_DENSITY_WEIGHT = 0.25
_CATEGORY_COVERAGE_WEIGHT = 0.20
_STRONG_FACT_WEIGHT = 0.25
_CONFLICT_WEIGHT = 0.10
_FRESHNESS_WEIGHT = 0.20

# Fact density: how many accepted facts per 1000 characters is "good".
_DENSITY_GOOD = 5.0   # ≥5 facts/kchar → 100
_DENSITY_OK = 1.5     # 1.5–5 → linear 40→100, <1.5 → linear 0→40

# All 12 trusted-fact categories.
_ALL_CATEGORIES = frozenset({
    "ADDRESS", "COORDINATES", "OPENING_HOURS", "TEMPORARY_CLOSURE",
    "TICKET_PRICE", "REFERENCE_SPEND", "RESERVATION_REQUIREMENT",
    "RESERVATION_ENTRY", "TRANSPORT_ADVICE", "WEATHER",
    "VENUE_ENVIRONMENT", "ATTRACTION_IDENTITY",
})


@dataclass(frozen=True, slots=True)
class QualityDimensions:
    fact_density: int       # 0–100
    category_coverage: int  # 0–100
    strong_fact_ratio: int  # 0–100
    conflict_rate: int      # 0–100 (higher = fewer conflicts)
    freshness_health: int   # 0–100


@dataclass(frozen=True, slots=True)
class GuideQualityScore:
    overall: int                       # 0–100
    dimensions: QualityDimensions
    label: str                         # "优质" / "可用" / "待完善"
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def compute_guide_quality(result: GuideImportResult) -> GuideQualityScore | None:
    """Return a quality score for an imported guide, or None when N/A.

    CITY_INTELLIGENCE imports are auto-collected and skipped.
    Guides with zero accepted facts receive overall=0.
    """
    if result.source_type == "CITY_INTELLIGENCE":
        return None

    accepted = result.trusted_facts
    merged = result.merge_decisions

    content_length = _content_length(result)
    accepted_count = len(accepted)

    if accepted_count == 0:
        return GuideQualityScore(
            overall=0,
            dimensions=QualityDimensions(0, 0, 0, 0, 0),
            label="待完善",
        )

    # ── Fact density ──────────────────────────────────────────────────
    density = accepted_count / max(content_length / 1000, 1)
    if density >= _DENSITY_GOOD:
        density_score = 100
    elif density >= _DENSITY_OK:
        density_score = round(40 + (density - _DENSITY_OK) / (_DENSITY_GOOD - _DENSITY_OK) * 60)
    else:
        density_score = round(density / _DENSITY_OK * 40)

    # ── Category coverage ─────────────────────────────────────────────
    covered = {f.category for f in accepted if f.category in _ALL_CATEGORIES}
    coverage_score = round(len(covered) / len(_ALL_CATEGORIES) * 100)

    # ── Strong fact ratio ─────────────────────────────────────────────
    strong = sum(1 for f in accepted if f.hard_constraint_eligible)
    strong_score = round(strong / accepted_count * 100)

    # ── Conflict rate ─────────────────────────────────────────────────
    if merged:
        conflict_count = sum(
            1 for d in merged
            if d.conflict_facts and len(d.conflict_facts) > 0
        )
        conflict_score = round(
            max(0, 1 - conflict_count / accepted_count) * 100
        )
    else:
        conflict_score = 100  # no merge → no conflicts

    # ── Freshness health ──────────────────────────────────────────────
    now = datetime.now(UTC)
    fresh = sum(1 for f in accepted if f.expires_at > now)
    freshness_score = round(fresh / accepted_count * 100)

    dimensions = QualityDimensions(
        fact_density=min(100, density_score),
        category_coverage=min(100, coverage_score),
        strong_fact_ratio=min(100, strong_score),
        conflict_rate=min(100, conflict_score),
        freshness_health=min(100, freshness_score),
    )

    overall = round(
        dimensions.fact_density * _FACT_DENSITY_WEIGHT
        + dimensions.category_coverage * _CATEGORY_COVERAGE_WEIGHT
        + dimensions.strong_fact_ratio * _STRONG_FACT_WEIGHT
        + dimensions.conflict_rate * _CONFLICT_WEIGHT
        + dimensions.freshness_health * _FRESHNESS_WEIGHT
    )

    if overall >= 80:
        label = "优质"
    elif overall >= 60:
        label = "可用"
    else:
        label = "待完善"

    return GuideQualityScore(overall=overall, dimensions=dimensions, label=label)


def _content_length(result: GuideImportResult) -> int:
    doc = result.normalized_document
    if doc is not None and doc.content:
        return len(doc.content)
    # Fall back to excerpt length for simple imports without normalized doc
    return len(result.excerpt) if result.excerpt else 1
