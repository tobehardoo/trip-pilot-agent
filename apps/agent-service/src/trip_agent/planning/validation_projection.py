"""Shared validation-state projection for every planning entry point.

B9.1 — one projection for Demo create, local replan, EDIT/ROLLBACK
candidates and repair: the same facts always produce the same
TripSkeleton / ValidationInputs shape, and no entry point ever fabricates
hotel confirmations, coordinates, POI ids or hard opening evidence.

Pure functions only: no clocks, no network, no persistence.
"""

from __future__ import annotations

from trip_agent.domain.shared import CHINA_TIME_ZONE, text_matches
from trip_agent.feasibility.inputs import (
    ActivityLocator,
    MealPlacementBinding,
    MealProjectionState,
    MealWindowType,
    OpeningHoursBinding,
    ValidationInputs,
    VisitDurationBinding,
)
from trip_agent.guide_intelligence.opening_evidence import (
    evidence_from_validated_fact,
)
from trip_agent.guide_intelligence.trusted_facts import ValidatedFact
from trip_agent.planning.daily_schedule import DayPlan
from trip_agent.planning.poi_quality import duration_profile_for
from trip_agent.planning.trip_skeleton import (
    ConfirmedAccommodation,
    GeoPoint,
    UnresolvedAccommodation,
    build_trip_skeleton,
)
from trip_agent.providers.map import Coordinates, Poi
from trip_agent.worker.contracts import AccommodationStatus, Itinerary

# Facts usable for opening bindings.  AMap provider evidence is never
# hard-constraint eligible (hard_constraint_eligible=False is preserved
# verbatim by _validated_fact), so it can never be upgraded into a hard
# window by this projection.
_OPENING_FACT_CATEGORIES = frozenset({"OPENING_HOURS", "TEMPORARY_CLOSURE"})

# The planner projects LUNCH then DINNER per day and never projects
# BREAKFAST (planning domain).  Bindings therefore zip against the same
# canonical order so windows pair with the right meal-type activity no
# matter which order the client declared them in.
_MEAL_TYPE_RANK = {"LUNCH": 0, "DINNER": 1}


def project_accommodation_status(
    itinerary: Itinerary,
    requested_accommodation_label: str | None,
    requested_place_ref: object | None = None,
) -> AccommodationStatus | None:
    """Derive the itinerary's accommodation resolution status for display.

    CONFIRMED when the user selected a precise provider candidate
    (``place_ref.providerPoiId``) — that POI identity is authoritative even
    when the planner did not project a hotel activity (e.g. DEMO), or when an
    ACCOMMODATION activity carries a provider POI id AND coordinates.
    Anything else (label only, or no accommodation node at all) is
    UNRESOLVED — never fabricated.  No label means the trip never asked for
    accommodation, so the field is omitted entirely.
    """
    if not requested_accommodation_label:
        return None
    place_ref = getattr(requested_place_ref, "provider_poi_id", None) or getattr(
        requested_place_ref, "providerPoiId", None
    )
    if place_ref:
        return AccommodationStatus(
            status="CONFIRMED",
            place_name=requested_accommodation_label,
        )
    for day in itinerary.days:
        for activity in day.activities:
            if activity.kind == "ACCOMMODATION":
                confirmed = (
                    activity.provider_poi_id is not None
                    and activity.coordinates is not None
                )
                return AccommodationStatus(
                    status="CONFIRMED" if confirmed else "UNRESOLVED",
                    place_name=requested_accommodation_label,
                )
    return AccommodationStatus(
        status="UNRESOLVED",
        place_name=requested_accommodation_label,
    )


def attach_accommodation_status(
    itinerary: Itinerary,
    requested_accommodation_label: str | None,
    requested_place_ref: object | None = None,
) -> Itinerary:
    """Return a wire copy of the itinerary carrying the accommodation status.

    The validation skeleton keeps deriving accommodation internally; this only
    decorates the emitted itinerary so Java/Web can render the hotel state.
    Returns the same object when there is nothing to attach.
    """
    status = project_accommodation_status(
        itinerary, requested_accommodation_label, requested_place_ref
    )
    if status is None:
        return itinerary
    return itinerary.model_copy(update={"accommodation": status})


def project_validation_state(
    itinerary: Itinerary,
    *,
    requested_accommodation_label: str | None,
    meal_windows: tuple[object, ...] = (),
    facts: tuple[object, ...] = (),
    meal_projection_state: MealProjectionState = MealProjectionState.COMPLETE,
) -> tuple[object, object]:
    """Project one itinerary onto its transient skeleton and validation inputs.

    Accommodation is inferred strictly from ACCOMMODATION activities that
    carry both a provider POI id and coordinates; anything else stays
    UNRESOLVED (never silently area-estimated).  Single-day itineraries
    produce zero overnight boundaries.  ``meal_projection_state`` lets an
    entry point that cannot resolve restaurants (e.g. Demo) declare its meal
    projection UNAVAILABLE instead of pretending bindings are complete.
    """
    day_plans = tuple(_day_plan(day) for day in itinerary.days)
    accommodations = _project_overnights(itinerary, requested_accommodation_label)
    skeleton = build_trip_skeleton(day_plans, accommodations)
    inputs = _project_validation_inputs(itinerary, meal_windows, facts, meal_projection_state)
    return skeleton, inputs


def _project_overnights(
    itinerary: Itinerary, requested_accommodation_label: str | None
) -> list[object]:
    accommodations: list[object] = []
    for from_day, to_day in zip(itinerary.days, itinerary.days[1:], strict=False):
        first = from_day.activities[-1] if from_day.activities else None
        second = to_day.activities[0] if to_day.activities else None
        confirmed = (
            _confirmed_overnight(first, second)
            if first is not None and second is not None
            else None
        )
        if confirmed is not None:
            accommodations.append(confirmed)
        else:
            accommodations.append(
                UnresolvedAccommodation(requested_label=requested_accommodation_label)
            )
    return accommodations


def _confirmed_overnight(first, second) -> ConfirmedAccommodation | None:
    candidates = (first, second)
    accommodation_nodes = tuple(
        activity
        for activity in candidates
        if getattr(activity, "kind", None) == "ACCOMMODATION"
        and activity.provider_poi_id is not None
        and activity.coordinates is not None
    )
    if not accommodation_nodes:
        return None
    anchor = accommodation_nodes[0]
    if any(
        activity.provider_poi_id != anchor.provider_poi_id
        or activity.coordinates != anchor.coordinates
        for activity in accommodation_nodes[1:]
    ):
        return None
    return ConfirmedAccommodation(
        label=anchor.title,
        provider_poi_id=anchor.provider_poi_id,
        coordinates=GeoPoint(
            longitude=float(anchor.coordinates.longitude),
            latitude=float(anchor.coordinates.latitude),
        ),
    )


def _day_plan(day) -> DayPlan:
    local_starts = tuple(
        activity.start_time.astimezone(CHINA_TIME_ZONE) for activity in day.activities
    )
    local_ends = tuple(activity.end_time.astimezone(CHINA_TIME_ZONE) for activity in day.activities)
    return DayPlan(
        date=day.date,
        day_type=day.day_type or "FULL_DAY",
        window_start_minute=min(value.hour * 60 + value.minute for value in local_starts),
        window_end_minute=max(value.hour * 60 + value.minute for value in local_ends),
        items=(),
        meal_demands=(),
        origin=None,
        accommodation_unknown=False,
        warnings=(),
    )


def _projected_meal_windows(meal_windows: tuple[object, ...]) -> tuple[object, ...]:
    """The windows the planner actually projects, in canonical meal order.

    DISABLED windows are never projected and BREAKFAST is outside the
    planning domain; both are excluded so they can never steal a binding
    from a meal the planner did place.  The remaining LUNCH/DINNER windows
    are sorted into the planner's emission order so positional zipping
    pairs each window with the right meal-type activity.
    """
    return tuple(
        sorted(
            (
                window
                for window in meal_windows
                if getattr(window, "meal_type", None) in {"LUNCH", "DINNER"}
                and getattr(window, "source", "USER") != "DISABLED"
            ),
            key=lambda window: _MEAL_TYPE_RANK.get(getattr(window, "meal_type", ""), 99),
        )
    )


def _project_validation_inputs(
    itinerary: Itinerary,
    meal_windows: tuple[object, ...],
    facts: tuple[object, ...],
    meal_projection_state: MealProjectionState,
) -> ValidationInputs:
    opening_bindings: list[OpeningHoursBinding] = []
    duration_bindings: list[VisitDurationBinding] = []
    meal_bindings: list[MealPlacementBinding] = []
    # B13_FIX R3 (P0-3): days whose MEAL activities carry no explicit meal
    # type cannot be bound by identity; the meal rule reports UNKNOWN for
    # them instead of guessing by position.
    unverified_meal_days: list[int] = []
    for day_index, day in enumerate(itinerary.days):
        meal_activities: list[tuple[ActivityLocator, object]] = []
        day_has_untyped_meal = False
        for activity_index, activity in enumerate(day.activities):
            locator = ActivityLocator(day_index, activity_index)
            if activity.kind in {"ATTRACTION", "EXPERIENCE"}:
                duration_bindings.append(
                    VisitDurationBinding(
                        activity=locator,
                        profile=duration_profile_for(_poi_from_activity(activity)),
                    )
                )
            if activity.kind == "MEAL":
                meal_activities.append((locator, activity))
                if activity.meal_type is None:
                    day_has_untyped_meal = True
            if activity.provider_poi_id is None:
                continue
            evidences = tuple(
                evidence
                for fact in facts
                if getattr(fact, "category", None) in _OPENING_FACT_CATEGORIES
                and text_matches(activity.title, f"{fact.statement} {fact.evidence}")
                for evidence in (
                    evidence_from_validated_fact(
                        validated_fact_from_planning_fact(fact), poi_key=activity.provider_poi_id
                    ),
                )
                if evidence is not None
            )
            if evidences:
                opening_bindings.append(
                    OpeningHoursBinding(
                        activity=locator,
                        poi_key=activity.provider_poi_id,
                        evidences=evidences,
                    )
                )
        projected = _projected_meal_windows(meal_windows)
        # B13_FIX R3 (P0-3): bind windows to MEAL activities by explicit
        # meal-type identity — never by position.  A window with no typed
        # activity stays unbound (the meal rule FAILs it as missing, which
        # is correct when the planner genuinely did not place it).  A day
        # with untyped MEAL activities is unverifiable, never positionally
        # guessed.
        if day_has_untyped_meal:
            unverified_meal_days.append(day_index)
            continue
        typed_activities: dict[str, ActivityLocator] = {}
        for locator, activity in meal_activities:
            if activity.meal_type is not None:
                existing = typed_activities.get(activity.meal_type)
                if existing is not None:
                    raise ValueError(
                        f"day {day.date} has duplicate {activity.meal_type} meal activities"
                    )
                typed_activities[activity.meal_type] = locator
        for window in projected:
            locator = typed_activities.get(window.meal_type)
            if locator is not None:
                meal_bindings.append(
                    MealPlacementBinding(
                        activity=locator,
                        meal_type=MealWindowType(window.meal_type),
                    )
                )
    return ValidationInputs(
        opening_hours_bindings=tuple(opening_bindings),
        visit_duration_bindings=tuple(duration_bindings),
        meal_placement_bindings=tuple(meal_bindings),
        meal_projection_state=meal_projection_state,
        unverified_meal_days=tuple(unverified_meal_days),
    )


def _poi_from_activity(activity) -> Poi:
    coordinates = activity.coordinates
    if coordinates is None or activity.provider_poi_id is None:
        raise ValueError("duration-applicable candidate activities need provider coordinates")
    return Poi(
        provider_id=activity.provider_poi_id,
        name=activity.title,
        coordinates=Coordinates(
            longitude=float(coordinates.longitude),
            latitude=float(coordinates.latitude),
        ),
        type_name=activity.type_name or "",
        type_code=activity.type_code or "",
        province="",
        city="",
        district="",
        address=activity.address or "",
    )


def validated_fact_from_planning_fact(fact) -> ValidatedFact:
    return ValidatedFact(
        fact_id=fact.fact_id,
        document_id=fact.fact_id,
        category=fact.category,
        statement=fact.statement,
        normalized_value=fact.normalized_value or {},
        evidence=fact.evidence,
        evidence_start=0,
        evidence_end=len(fact.evidence),
        confidence=1.0 if fact.hard_constraint_eligible else 0.5,
        checked_at=fact.checked_at,
        expires_at=fact.expires_at,
        effective_date=fact.effective_date,
        source_type=fact.source_type,
        source_name=fact.source_name,
        source_url=str(fact.source_url) if fact.source_url is not None else None,
        reliability_level=fact.reliability_level,
        source_reviewed=fact.source_reviewed,
        hard_constraint_eligible=fact.hard_constraint_eligible,
    )
