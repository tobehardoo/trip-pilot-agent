"""L1 multi-source evidence fusion into :class:`TrustedConclusion`.

This module is the decision-enabling layer: it merges L0 facts (the
:class:`~trip_agent.guide_intelligence.trusted_facts.ValidatedFact` load layer)
about the same ``(entity, property)`` into a single, decisive conclusion with
an explicit status, a confidence, and full source provenance.

Design rules (M0, deterministic, pure, no I/O — acquisition is upstream):

- consistent facts -> take the highest-reliability / newest value;
- conflicting facts -> compare reliability first (configurable
  ``RELIABILITY_ORDER``), then ``collected_at``; a tie on both is
  ``CONFLICTING`` and is NOT adopted;
- a single weak source -> low-confidence ``UNVERIFIED``.

``guide_fact_bonus`` is the same reliability x freshness surface the L3
ranking tier consumes, kept here so ranking and fusion can never disagree on
what "strong" means.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from trip_agent.guide_intelligence.trusted_facts import ValidatedFact

type ConclusionStatus = Literal["VERIFIED", "UNVERIFIED", "UNKNOWN", "CONFLICTING"]

# Configurable reliability ordering (highest first).  Fusion compares
# reliability with this order before falling back to collected_at.  The
# canonical M0 vocabulary, plus legacy levels aliased into the same scale.
RELIABILITY_ORDER: tuple[str, ...] = (
    "OFFICIAL_GOV",
    "OFFICIAL_PORTAL",
    "OPEN_DATA",
    "CURATED",
    "UGC",
    "OCR_UNVERIFIED",
)

# Legacy guide_intelligence / acquisition reliability_level values mapped onto
# the canonical scale so pre-existing facts rank sensibly beside new ones.
_LEGACY_RANK: dict[str, int] = {
    # same tier as OFFICIAL_PORTAL
    "OFFICIAL": 5,
    "OFFICIAL_ATTRACTION": 5,
    "OFFICIAL_TOURISM": 5,
    # CURATED / OPEN_DATA tier
    "CURATED": 3,
    "MAP_PROVIDER": 3,
    "WEATHER_PROVIDER": 3,
    "PUBLIC_GUIDE": 3,
    # UGC tier
    "COMMUNITY": 2,
}

# A single source at or above this rank is treated as strong (verified).
_CURATED_TIER = 3

# L3 ranking: how long a fact stays "fresh" before the staleness penalty.
FRESH_WINDOW_DAYS = 30
_STALE_PENALTY = 12
_GUIDE_BONUS_BY_RANK: dict[int, int] = {
    6: 30,
    5: 28,
    4: 25,
    3: 18,
    2: 10,
    1: 6,
    0: 4,
}

_UNKNOWN_ENTITY = "_unknown_entity"


def reliability_rank(reliability_level: str) -> int:
    """Rank a reliability level on the configurable scale (higher == stronger)."""
    try:
        return len(RELIABILITY_ORDER) - RELIABILITY_ORDER.index(reliability_level)
    except ValueError:
        return _LEGACY_RANK.get(reliability_level, 0)


def freshness_bucket(collected_at: datetime, *, now: datetime | None = None) -> int:
    """Return 0 when fresh, 1 when outside the fresh window.

    ``now`` is an explicit reference clock for determinism; ``None`` treats
    every fact as fresh (no clock injected).
    """
    if now is None:
        return 0
    try:
        age = now - collected_at
    except TypeError:
        return 0
    if age.total_seconds() < 0:
        return 0
    return 0 if age.days <= FRESH_WINDOW_DAYS else 1


def guide_fact_bonus(
    reliability_level: str,
    collected_at: datetime,
    *,
    now: datetime | None = None,
) -> int:
    """Reliability x freshness guide-match bonus (0..30), shared with L3 ranking."""
    rank = reliability_rank(reliability_level)
    bonus = _GUIDE_BONUS_BY_RANK.get(rank, 4)
    if freshness_bucket(collected_at, now=now) == 1:
        bonus -= _STALE_PENALTY
    return max(0, bonus)


@dataclass(frozen=True, slots=True)
class EvidenceSourceRef:
    """One source behind a conclusion."""

    source_id: str
    reliability_level: str
    url: str | None
    collected_at: datetime


@dataclass(frozen=True, slots=True)
class TrustedConclusion:
    """A fused, decision-ready conclusion for one (entity, property)."""

    entity: str
    property: str
    value: Mapping[str, object] | None
    status: ConclusionStatus
    confidence: float
    sources: tuple[EvidenceSourceRef, ...]


def fuse_facts(facts: Iterable[ValidatedFact]) -> tuple[TrustedConclusion, ...]:
    """Fuse multi-source facts into conclusions, grouped by (entity, property).

    Pure and deterministic: no I/O, no clock.  Returns an empty tuple for empty
    input.
    """
    fact_list = tuple(facts)
    if not fact_list:
        return ()
    grouped: dict[tuple[str, str], list[ValidatedFact]] = {}
    for fact in fact_list:
        key = (fact.entity or _UNKNOWN_ENTITY, fact.category)
        grouped.setdefault(key, []).append(fact)
    conclusions = [
        _fuse_group(entity, property_, group)
        for (entity, property_), group in grouped.items()
    ]
    conclusions.sort(key=lambda item: (item.entity, item.property))
    return tuple(conclusions)


def _fuse_group(
    entity: str,
    property_: str,
    facts: list[ValidatedFact],
) -> TrustedConclusion:
    distinct_values = {_value_key(fact.normalized_value) for fact in facts}
    winner = _pick_winner(facts)
    distinct_sources = _distinct_source_count(facts)
    conflicted = len(distinct_values) > 1

    if conflicted and not _decidable(facts, winner):
        return TrustedConclusion(
            entity=entity,
            property=property_,
            value=None,
            status="CONFLICTING",
            confidence=0.15,
            sources=_source_refs(facts),
        )

    status = "VERIFIED" if _verified(winner, distinct_sources) else "UNVERIFIED"
    confidence = _confidence(winner, distinct_sources, conflicted=conflicted)
    return TrustedConclusion(
        entity=entity,
        property=property_,
        value=winner.normalized_value,
        status=status,
        confidence=confidence,
        sources=_source_refs(facts),
    )


def _pick_winner(facts: list[ValidatedFact]) -> ValidatedFact:
    """Deterministic winner: highest reliability, then newest, then fact id."""
    return max(
        facts,
        key=lambda fact: (
            reliability_rank(fact.reliability_level),
            fact.checked_at,
            fact.fact_id,
        ),
    )


def _verified(winner: ValidatedFact, distinct_sources: int) -> bool:
    """A multi-source consensus, or any single source at CURATED-or-stronger."""
    return distinct_sources >= 2 or reliability_rank(winner.reliability_level) >= _CURATED_TIER


def _decidable(facts: list[ValidatedFact], winner: ValidatedFact) -> bool:
    """Whether conflicting facts can be resolved by reliability then freshness.

    Compare reliability first; among the top reliability, only a single newest
    ``collected_at`` yields a decidable outcome (otherwise CONFLICTING).
    """
    best_rank = reliability_rank(winner.reliability_level)
    top_by_rank = [
        fact for fact in facts if reliability_rank(fact.reliability_level) == best_rank
    ]
    newest = max(fact.checked_at for fact in top_by_rank)
    return sum(1 for fact in top_by_rank if fact.checked_at == newest) == 1


def _confidence(
    winner: ValidatedFact,
    distinct_sources: int,
    *,
    conflicted: bool,
) -> float:
    rank = reliability_rank(winner.reliability_level)
    score = 0.40 + 0.07 * rank + 0.04 * min(distinct_sources - 1, 5)
    if conflicted:
        score -= 0.10
    return round(min(score, 0.98), 3)


def _distinct_source_count(facts: list[ValidatedFact]) -> int:
    return len({(fact.source_id, fact.source_url or fact.source_name) for fact in facts})


def _source_refs(facts: list[ValidatedFact]) -> tuple[EvidenceSourceRef, ...]:
    seen: set[tuple] = set()
    refs: list[EvidenceSourceRef] = []
    for fact in facts:
        key = (fact.source_id, fact.source_url or fact.source_name)
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            EvidenceSourceRef(
                source_id=fact.source_id or fact.source_name or fact.source_type,
                reliability_level=fact.reliability_level,
                url=fact.source_url,
                collected_at=fact.checked_at,
            )
        )
    refs.sort(key=lambda ref: (ref.source_id, ref.collected_at))
    return tuple(refs)


def _value_key(value: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(k), repr(v)) for k, v in value.items()))