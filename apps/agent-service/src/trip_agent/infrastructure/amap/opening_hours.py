"""Opening-hours evidence projection and candidate constraints.

Pure functions extracted from the AMap planning provider: they translate
recalled POIs / planning-context facts into opening evidence for candidate
ranking, and attach resolver-verified opening constraints to candidates for
the daily scheduler.  No I/O and no provider state — every call site is the
provider's orchestration method.
"""

from datetime import UTC, datetime, timedelta

from trip_agent.domain.shared import text_matches
from trip_agent.guide_intelligence.travel_entities import (
    FactProvenance,
    FactValue,
    TravelEntityLocation,
    build_attraction,
)
from trip_agent.infrastructure.amap.poi_recall import FetchedPoi
from trip_agent.providers.map import Poi


def resolver_clock(facts: tuple[object, ...]) -> datetime:
    """The single freshness clock for opening resolution.

    Uses the latest evidence observation as the resolver 'as-of' moment so
    the resolver never depends on wall-clock time during planning.
    """
    checked = tuple(
        getattr(fact, "checked_at", None)
        for fact in facts
        if getattr(fact, "checked_at", None) is not None
    )
    if checked:
        return max(checked)
    return datetime.now(UTC)


def amap_opening_value(poi: Poi, fetched_at: datetime) -> tuple[str, FactProvenance] | None:
    """Project AMap business opening text onto a POI as provider evidence.

    ``opentime_today`` is today-scoped data: its effective date is the
    ``ProviderSuccess.fetched_at`` Asia/Shanghai local date.  The fetch time
    is passed explicitly across the projection boundary and never replaced
    by a downstream clock.
    """
    text = poi.business_hours_today or poi.business_hours_week
    if not text:
        return None
    provenance = FactProvenance(
        source="AMAP",
        source_type="PROVIDER",
        fetched_at=fetched_at,
        valid_until=fetched_at + timedelta(days=14),
        confidence=0.8,
    )
    return text, provenance


def entity_facts_for_pois(
    pois: tuple[FetchedPoi, ...],
    command: object,
) -> tuple:
    """Project fresh planning-context opening-hour facts onto recalled POIs.

    The event contract predates ``cityAdcode``; keep that field explicitly unknown
    until the producer supplies the structured region, while still preserving the
    fact's source and expiry for candidate explanations.
    """
    context = command.payload.planning_context  # type: ignore[attr-defined]
    if context is None:
        return ()
    opening_facts = tuple(
        fact for fact in context.facts if fact.category == "OPENING_HOURS" and not fact.stale
    )
    entities = []
    for fetched in pois:
        poi = fetched.poi
        fact = next(
            (
                item
                for item in opening_facts
                if text_matches(poi.name, f"{item.statement} {item.evidence}")
            ),
            None,
        )
        if fact is None:
            amap_known = amap_opening_value(poi, fetched.fetched_at)
            if amap_known is None:
                continue
            text, provenance = amap_known
            entities.append(
                build_attraction(
                    city_adcode=None,
                    provider_poi_id=poi.provider_id,
                    name=poi.name,
                    category="ATTRACTION",
                    location=TravelEntityLocation(
                        poi.coordinates.longitude,
                        poi.coordinates.latitude,
                        poi.address,
                    ),
                    opening_hours=FactValue.known(text, provenance),
                )
            )
            continue
        source_type = "OFFICIAL" if fact.source_reviewed else "GUIDE"
        provenance = FactProvenance(
            source=fact.source_name,
            source_type=source_type,
            fetched_at=fact.checked_at,
            valid_until=fact.expires_at,
            confidence=1.0 if fact.source_reviewed else 0.7,
        )
        entities.append(
            build_attraction(
                city_adcode=None,
                provider_poi_id=poi.provider_id,
                name=poi.name,
                category="ATTRACTION",
                location=TravelEntityLocation(
                    poi.coordinates.longitude,
                    poi.coordinates.latitude,
                    poi.address,
                ),
                opening_hours=FactValue.known(fact.statement, provenance),
            )
        )
    return tuple(entities)


def with_opening_availability(
    candidates: tuple,
    context: object,
    trip_date: object,
) -> tuple:
    """Attach verified opening constraints to candidates (B9.2).

    Only resolver VERIFIED_WINDOW / VERIFIED_CLOSED verdicts with
    ``hard_constraint_eligible=True`` constrain placement; AMap provider
    evidence is never hard-eligible, so it can never be upgraded here.
    """
    from dataclasses import replace

    from trip_agent.guide_intelligence.opening_evidence import (
        evidence_from_validated_fact,
    )
    from trip_agent.guide_intelligence.opening_resolver import (
        resolve_opening_hours,
    )
    from trip_agent.planning.daily_schedule import (
        opening_availability_from_resolved,
    )
    from trip_agent.planning.validation_projection import (
        validated_fact_from_planning_fact,
    )

    facts = tuple(getattr(context, "facts", ()))
    opening_facts = tuple(
        fact
        for fact in facts
        if getattr(fact, "category", None) in {"OPENING_HOURS", "TEMPORARY_CLOSURE"}
    )
    if not opening_facts:
        return candidates
    updated: list = []
    for candidate in candidates:
        evidences = tuple(
            evidence
            for fact in opening_facts
            if text_matches(candidate.title, f"{fact.statement} {fact.evidence}")
            for evidence in (
                evidence_from_validated_fact(
                    validated_fact_from_planning_fact(fact),
                    poi_key=candidate.poi_id,
                ),
            )
            if evidence is not None
        )
        if not evidences:
            updated.append(candidate)
            continue
        resolved = resolve_opening_hours(
            evidences,
            poi_key=candidate.poi_id,
            trip_date=trip_date,
            resolver_as_of=resolver_clock(facts),
        )
        availability = opening_availability_from_resolved(resolved)
        if availability.kind == "UNKNOWN":
            updated.append(candidate)
            continue
        updated.append(replace(candidate, opening=availability))
    return tuple(updated)
