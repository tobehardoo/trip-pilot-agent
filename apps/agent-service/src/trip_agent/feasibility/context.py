"""ValidationContext — the immutable, deterministic input to hard rules.

A context bundles the command, the itinerary and the pre-computed budget
view.  It deliberately contains no clock, network client, provider
adapter, database session or global mutable state, so every rule can be
re-run byte-for-byte identically.

``BudgetContext`` and ``build_budget_context`` live here (not in
``trip_agent.evaluation.rules``) so feasibility never imports evaluation;
the evaluation module re-exports them for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from trip_agent.worker.contracts import (
    Itinerary,
    PlanningCandidateValidationCommand,
    PlanningCreateCommand,
    PlanningReplanCommand,
)

if TYPE_CHECKING:
    from trip_agent.feasibility.inputs import ValidationInputs
    from trip_agent.planning.trip_skeleton import TripSkeleton


@dataclass(frozen=True, slots=True)
class BudgetContext:
    """Normalised budget data extracted once for all rules."""

    budget_amount: Decimal | None
    estimated_total_cost: Decimal
    budget_ratio: float | None  # None when budget not specified


def build_budget_context(
    command: PlanningCreateCommand | PlanningReplanCommand | PlanningCandidateValidationCommand,
    itinerary: Itinerary,
) -> BudgetContext:
    """Derive the budget view from command constraints and itinerary cost.

    Semantics are locked to the legacy evaluation helper: a non-positive or
    missing budget yields ``budget_ratio=None`` (rule NOT_APPLICABLE).
    """
    budget_amount = command.payload.trip.constraints.budget_amount
    cost = itinerary.estimated_total_cost
    ratio = None
    if budget_amount is not None and budget_amount > 0:
        ratio = float(cost / budget_amount)
    return BudgetContext(
        budget_amount=budget_amount,
        estimated_total_cost=cost,
        budget_ratio=ratio,
    )


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Everything a hard rule may read.  Immutable by construction."""

    command: PlanningCreateCommand | PlanningReplanCommand | PlanningCandidateValidationCommand
    itinerary: Itinerary
    budget: BudgetContext
    # B4B: transient planning aggregate supplied by the caller when the
    # provider produced one; None keeps legacy callers compatible.  Rules
    # must treat None as an evidence gap (UNKNOWN), never as a defect.
    trip_skeleton: TripSkeleton | None = None
    # B5: transient evidence/placement inputs; None means "no inputs were
    # provided" (rules report UNKNOWN), never a defect.
    validation_inputs: ValidationInputs | None = None
    # B5: the caller-supplied validation instant; rules use it instead of a
    # clock.  None is allowed for direct rule tests and means evidence that
    # depends on "now" cannot be judged (UNKNOWN).
    validation_time: datetime | None = None

    def __post_init__(self) -> None:
        inputs = self.validation_inputs
        if inputs is None:
            return
        days = self.itinerary.days
        for binding in inputs.opening_hours_bindings:
            self._validate_locator(binding.activity, days, None)
            activity = days[binding.activity.day_index].activities[
                binding.activity.activity_index
            ]
            if activity.provider_poi_id != binding.poi_key:
                raise ValueError(
                    "opening-hours binding poi_key must match the target activity "
                    "provider_poi_id"
                )
        for binding in inputs.visit_duration_bindings:
            self._validate_locator(binding.activity, days, None)
            activity = days[binding.activity.day_index].activities[
                binding.activity.activity_index
            ]
            if activity.kind not in {"ATTRACTION", "EXPERIENCE"}:
                raise ValueError(
                    "visit duration bindings may only target ATTRACTION/EXPERIENCE "
                    "activities"
                )
        for binding in inputs.meal_placement_bindings:
            self._validate_locator(binding.activity, days, "MEAL")

    @staticmethod
    def _validate_locator(
        locator: object,
        days: tuple,
        expected_kind: str | None,
    ) -> None:
        from trip_agent.feasibility.inputs import ActivityLocator

        if not isinstance(locator, ActivityLocator):
            raise ValueError("bindings must use ActivityLocator instances")
        if locator.day_index >= len(days):
            raise ValueError("binding day_index is out of range")
        activities = days[locator.day_index].activities
        if locator.activity_index >= len(activities):
            raise ValueError("binding activity_index is out of range")
        if expected_kind is not None:
            actual = activities[locator.activity_index].kind
            if actual != expected_kind:
                raise ValueError(
                    f"binding must target a {expected_kind} activity, got {actual}"
                )
