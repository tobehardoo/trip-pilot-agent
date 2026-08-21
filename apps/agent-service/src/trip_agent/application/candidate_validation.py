"""B8 candidate re-validation adapter.

The Java edit/rollback boundary owns the immutable candidate.  This adapter
refreshes its impacted routes through the configured planning provider and
rebuilds the transient TripSkeleton/ValidationInputs required by the
canonical hard validator.  It never persists state and never upgrades soft
provider data into hard evidence.

B9.1 — the projection itself now lives in the shared
``trip_agent.planning.validation_projection`` module so Demo create,
local replan, edit/rollback candidates and repair all derive the same
projection semantics from the same code.
"""

from __future__ import annotations

from trip_agent.domain.planning.protocols import (
    PlanningProvider,
    PlanningRepairRequest,
    PlanningResult,
)
from trip_agent.planning.validation_projection import project_validation_state
from trip_agent.worker.contracts import (
    Itinerary,
    PlanningCandidateValidationCommand,
    wire_provider_for_snapshot,
)


class CandidateValidationProvider:
    """Refresh and project one EDIT/ROLLBACK candidate for validation."""

    def __init__(self, delegate: PlanningProvider | None = None) -> None:
        self._delegate = delegate

    async def validate(self, command: PlanningCandidateValidationCommand) -> PlanningResult:
        if self._delegate is None:
            result = PlanningResult(
                provider=wire_provider_for_snapshot(command.payload.itinerary),
                itinerary=_candidate_itinerary(command),
            )
        else:
            # Candidate and replan commands deliberately share the itinerary
            # and impacted-date boundary. Provider implementations read only
            # those fields and return a normal PlanningResult.
            result = await self._delegate.replan(command)
        return _with_projection(command, result)

    async def repair(self, request: PlanningRepairRequest) -> PlanningResult:
        if self._delegate is None:
            return request.candidate
        repaired = await self._delegate.repair(request)
        command = request.command
        if not isinstance(command, PlanningCandidateValidationCommand):
            return repaired
        return _with_projection(command, repaired)


def _with_projection(
    command: PlanningCandidateValidationCommand, result: PlanningResult
) -> PlanningResult:
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
    requested = command.payload.trip.constraints.accommodation
    context = command.payload.planning_context
    facts = context.facts if context is not None else ()
    meal_windows = tuple(command.payload.trip.constraints.meal_windows)
    return project_validation_state(
        itinerary,
        requested_accommodation_label=(requested.place_name if requested is not None else None),
        meal_windows=meal_windows,
        facts=facts,
    )
