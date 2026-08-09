"""Opening-hours evidence: a uniform, provenance-complete input for the resolver.

The resolver never infers provenance.  Every candidate fact is converted by
exactly one adapter into an :class:`OpeningHoursEvidence` carrying its own
reliability, review status, hard-constraint eligibility, confidence, and
freshness timestamps.

``poi_key`` is always injected by the calling projection layer (a POI-matched
fact or a provider POI); adapters never recompute a canonical key themselves.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from trip_agent.domain.shared import CHINA_TIME_ZONE
from trip_agent.guide_intelligence.models import TravelFact
from trip_agent.guide_intelligence.opening_hours import (
    ParsedOpeningHours,
    parse_amap_week_schedule,
    parse_opening_text,
    parse_opening_value,
)
from trip_agent.guide_intelligence.trusted_facts import ValidatedFact
from trip_agent.providers.map import Poi

type EvidenceKind = Literal["OPENING_HOURS", "TEMPORARY_CLOSURE"]


@dataclass(frozen=True, slots=True)
class OpeningHoursEvidence:
    kind: EvidenceKind
    poi_key: str
    parsed_hours: ParsedOpeningHours | None
    raw: str
    effective_date: date | None
    source_ref: str
    reliability_level: str
    source_reviewed: bool
    hard_constraint_eligible: bool
    confidence: float
    checked_at: datetime
    expires_at: datetime


def evidence_from_validated_fact(
    fact: ValidatedFact, *, poi_key: str | None
) -> OpeningHoursEvidence | None:
    """Adapter for trusted-fact pipeline facts (OPENING_HOURS /
    TEMPORARY_CLOSURE).  Facts without an injected ``poi_key`` are dropped —
    the resolver must not guess entity ownership."""
    if poi_key is None:
        return None
    if fact.category == "OPENING_HOURS":
        return OpeningHoursEvidence(
            kind="OPENING_HOURS",
            poi_key=poi_key,
            parsed_hours=parse_opening_value(fact.normalized_value),
            raw=fact.statement,
            effective_date=fact.effective_date,
            source_ref=fact.fact_id,
            reliability_level=fact.reliability_level,
            source_reviewed=fact.source_reviewed,
            hard_constraint_eligible=fact.hard_constraint_eligible,
            confidence=fact.confidence,
            checked_at=fact.checked_at,
            expires_at=fact.expires_at,
        )
    if fact.category == "TEMPORARY_CLOSURE":
        return OpeningHoursEvidence(
            kind="TEMPORARY_CLOSURE",
            poi_key=poi_key,
            parsed_hours=None,
            raw=fact.statement,
            effective_date=fact.effective_date,
            source_ref=fact.fact_id,
            reliability_level=fact.reliability_level,
            source_reviewed=fact.source_reviewed,
            hard_constraint_eligible=fact.hard_constraint_eligible,
            confidence=fact.confidence,
            checked_at=fact.checked_at,
            expires_at=fact.expires_at,
        )
    return None


def evidence_from_amap_poi(
    poi: Poi, *, poi_key: str, fetched_at: datetime
) -> tuple[OpeningHoursEvidence, ...]:
    """Adapter for AMap POI ``business`` opening text.

    ``opentime_today`` becomes TODAY-scoped evidence bound to the
    ``ProviderSuccess.fetched_at`` Asia/Shanghai local date (the fetch time
    is passed explicitly across the adapter boundary, never a downstream
    clock); the week schedule becomes WEEKLY evidence only when parseable,
    otherwise its raw text survives as UNKNOWN evidence.
    """
    fetched_local = fetched_at.astimezone(CHINA_TIME_ZONE)
    evidences: list[OpeningHoursEvidence] = []
    if poi.business_hours_today:
        evidences.append(
            OpeningHoursEvidence(
                kind="OPENING_HOURS",
                poi_key=poi_key,
                parsed_hours=parse_opening_text(
                    poi.business_hours_today, scope="TODAY"
                ),
                raw=poi.business_hours_today,
                effective_date=fetched_local.date(),
                source_ref=poi.provider_id,
                reliability_level="MAP_PROVIDER",
                source_reviewed=False,
                hard_constraint_eligible=False,
                confidence=0.8,
                checked_at=fetched_at,
                expires_at=fetched_at + timedelta(days=1),
            )
        )
    if poi.business_hours_week:
        evidences.append(
            OpeningHoursEvidence(
                kind="OPENING_HOURS",
                poi_key=poi_key,
                parsed_hours=parse_amap_week_schedule(poi.business_hours_week),
                raw=poi.business_hours_week,
                effective_date=None,
                source_ref=poi.provider_id,
                reliability_level="MAP_PROVIDER",
                source_reviewed=False,
                hard_constraint_eligible=False,
                confidence=0.8,
                checked_at=fetched_at,
                expires_at=fetched_at + timedelta(days=14),
            )
        )
    return tuple(evidences)


def evidence_from_travel_fact(
    fact: TravelFact, *, poi_key: str | None, source_name: str
) -> OpeningHoursEvidence | None:
    """Adapter for City Intelligence TIMING facts carrying structured
    opening data.  Provenance is fixed (MAP_PROVIDER, unreviewed, never hard-
    constraint eligible) and never guessed from the fact."""
    if fact.category != "TIMING" or fact.normalized_value is None:
        return None
    if poi_key is None:
        return None
    parsed = parse_opening_value(fact.normalized_value)
    effective_date = fact.effective_date
    if parsed is not None and parsed.scope == "TODAY":
        raw_date = fact.normalized_value.get("effectiveDate")
        if isinstance(raw_date, str):
            with suppress(ValueError):
                effective_date = date.fromisoformat(raw_date)
    return OpeningHoursEvidence(
        kind="OPENING_HOURS",
        poi_key=poi_key,
        parsed_hours=parsed,
        raw=fact.statement,
        effective_date=effective_date,
        source_ref=source_name,
        reliability_level="MAP_PROVIDER",
        source_reviewed=False,
        hard_constraint_eligible=False,
        confidence=fact.confidence,
        checked_at=fact.observed_at,
        expires_at=fact.expires_at,
    )
