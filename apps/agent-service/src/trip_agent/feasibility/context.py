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
from decimal import Decimal
from typing import TYPE_CHECKING

from trip_agent.worker.contracts import (
    Itinerary,
    PlanningCreateCommand,
    PlanningReplanCommand,
)

if TYPE_CHECKING:
    from trip_agent.planning.trip_skeleton import TripSkeleton


@dataclass(frozen=True, slots=True)
class BudgetContext:
    """Normalised budget data extracted once for all rules."""

    budget_amount: Decimal | None
    estimated_total_cost: Decimal
    budget_ratio: float | None  # None when budget not specified


def build_budget_context(
    command: PlanningCreateCommand | PlanningReplanCommand,
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

    command: PlanningCreateCommand | PlanningReplanCommand
    itinerary: Itinerary
    budget: BudgetContext
    # B4B: transient planning aggregate supplied by the caller when the
    # provider produced one; None keeps legacy callers compatible.  Rules
    # must treat None as an evidence gap (UNKNOWN), never as a defect.
    trip_skeleton: TripSkeleton | None = None
