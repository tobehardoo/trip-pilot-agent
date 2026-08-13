"""B8 candidate re-validation adapter.

The Java edit/rollback boundary owns the immutable candidate.  This adapter
refreshes its impacted routes through the configured planning provider and
rebuilds the transient TripSkeleton/ValidationInputs required by the
canonical hard validator.  It never persists state and never upgrades soft
provider data into hard evidence.
"""

from __future__ import annotations

from trip_agent.domain.planning.protocols import (
    PlanningProvider,
    PlanningRepairRequest,
    PlanningResult,
)
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
from trip_agent.worker.contracts import (
    Itinerary,
    PlanningCandidateValidationCommand,
)


class CandidateValidationProvider:
    """Refresh and project one EDIT/ROLLBACK candidate for validation."""

    def __init__(self, delegate: PlanningProvider | None = None) -> None:
        self._delegate = delegate

    async def validate(
        self, command: PlanningCandidateValidationCommand
    ) -> PlanningResult:
        if self._delegate is None:
            result = PlanningResult(
                provider=command.payload.itinerary.provider,
                itinerary=_candidate_itinerary(command),
            )
        else:
            # Candidate and replan commands deliberately share the itinerary
            # and impacted-date boundary. Provider implementations read only
            # those fields and return a normal PlanningResult.
            result = await self._delegate.replan(command)
        skeleton, inputs = _project_validation_state(command, result.itinerary)
        return PlanningResult(
            provider=result.provider,
            itinerary=result.itinerary,
            guide_fact_ids=result.guide_fact_ids,
            requested_provider_mode=result.requested_provider_mode,
            primary_provider=result.primary_provider,
            actual_providers=result.actual_providers,
            fallback_attempted=result.fallback_attempted,
            fallback_succeeded=result.fallback_succeeded,
            fallback_reason=result.fallback_reason,
            fallback_operations=result.fallback_operations,
            trip_skeleton=skeleton,
            validation_inputs=inputs,
        )

    async def repair(self, request: PlanningRepairRequest) -> PlanningResult:
        if self._delegate is None:
            return request.candidate
        repaired = await self._delegate.repair(request)
        command = request.command
        if not isinstance(command, PlanningCandidateValidationCommand):
            return repaired
        skeleton, inputs = _project_validation_state(command, repaired.itinerary)
        return PlanningResult(
            provider=repaired.provider,
            itinerary=repaired.itinerary,
            guide_fact_ids=repaired.guide_fact_ids,
            requested_provider_mode=repaired.requested_provider_mode,
            primary_provider=repaired.primary_provider,
            actual_providers=repaired.actual_providers,
            fallback_attempted=repaired.fallback_attempted,
            fallback_succeeded=repaired.fallback_succeeded,
            fallback_reason=repaired.fallback_reason,
            fallback_operations=repaired.fallback_operations,
            trip_skeleton=skeleton,
            validation_inputs=inputs,
        )


def _candidate_itinerary(command: PlanningCandidateValidationCommand) -> Itinerary:
    snapshot = command.payload.itinerary
    return Itinerary(
        title=snapshot.title,
        days=tuple(day.to_itinerary_day() for day in snapshot.days),
        estimated_total_cost=snapshot.estimated_total_cost,
    )


def _project_validation_state(
    command: PlanningCandidateValidationCommand,
    itinerary: Itinerary,
):
    day_plans = tuple(_day_plan(day) for day in itinerary.days)
    accommodations = []
    requested = command.payload.trip.constraints.accommodation
    for from_day, to_day in zip(itinerary.days, itinerary.days[1:], strict=False):
        first = from_day.activities[-1]
        second = to_day.activities[0]
        confirmed = _confirmed_overnight(first, second)
        if confirmed is not None:
            accommodations.append(
                confirmed
            )
        else:
            accommodations.append(
                UnresolvedAccommodation(
                    requested_label=(requested.place_name if requested is not None else None)
                )
            )
    skeleton = build_trip_skeleton(day_plans, accommodations)
    return skeleton, _validation_inputs(command, itinerary)


def _confirmed_overnight(first, second) -> ConfirmedAccommodation | None:
    candidates = (first, second)
    accommodation_nodes = tuple(
        activity
        for activity in candidates
        if activity.kind == "ACCOMMODATION"
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
    local_ends = tuple(
        activity.end_time.astimezone(CHINA_TIME_ZONE) for activity in day.activities
    )
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


def _validation_inputs(
    command: PlanningCandidateValidationCommand,
    itinerary: Itinerary,
) -> ValidationInputs:
    opening_bindings: list[OpeningHoursBinding] = []
    duration_bindings: list[VisitDurationBinding] = []
    meal_bindings: list[MealPlacementBinding] = []
    context = command.payload.planning_context
    facts = context.facts if context is not None else ()
    meal_windows = tuple(command.payload.trip.constraints.meal_windows)
    for day_index, day in enumerate(itinerary.days):
        meal_activities = []
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
                meal_activities.append(locator)
            if activity.provider_poi_id is None:
                continue
            evidences = tuple(
                evidence
                for fact in facts
                if fact.category in {"OPENING_HOURS", "TEMPORARY_CLOSURE"}
                and text_matches(activity.title, f"{fact.statement} {fact.evidence}")
                for evidence in (
                    evidence_from_validated_fact(
                        _validated_fact(fact), poi_key=activity.provider_poi_id
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
        for window, locator in zip(meal_windows, meal_activities, strict=False):
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
        meal_projection_state=MealProjectionState.COMPLETE,
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


def _validated_fact(fact) -> ValidatedFact:
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
