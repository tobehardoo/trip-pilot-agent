"""P2.2: confirmed slots → deterministic planning pipeline → itinerary draft.

The demo builder turns the confirmed slots into a valid
``PlanningCreateCommand`` (schemaVersion 2) and runs the demo provider — the
same deterministic pipeline the async planning path uses, so the agent's
draft is a real itinerary object, not a text sketch.

Values the schema cannot accept (free-text dates, non-numeric budgets) fail
closed with ``ValueError`` — the tool maps those to structured failures and
the agent asks the user again instead of guessing.  Planner-required enums
that the demo skeleton does not consume (traveler_type / pace / mobility)
get neutral defaults; a real-provider builder must require normalized values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4, uuid5

from trip_agent.agent.state import ConstraintSlots
from trip_agent.domain.planning.protocols import PlanningResult
from trip_agent.domain.shared import normalize_trip_date
from trip_agent.feasibility.validator import run_validation
from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider
from trip_agent.worker.contracts import (
    Itinerary,
    PlanningCreateCommand,
    TripConstraints,
    TripSnapshot,
)

_PACES = {"RELAXED", "BALANCED", "INTENSIVE"}


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _optional_int(value: Any, *, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def build_demo_command(
    slots: ConstraintSlots,
    *,
    trip_id: str | None = None,
    today: date | None = None,
) -> PlanningCreateCommand:
    """Project confirmed slots onto a valid demo planning command.

    Raises ``ValueError`` with a stable prefix when a required value cannot
    be normalized — the tool layer maps that to a structured failure.
    """
    values = slots.confirmed_values()
    destination = str(values.get("destination") or "").strip()
    if not destination:
        raise ValueError("DESTINATION_MISSING: no confirmed destination")
    start = normalize_trip_date(values.get("start_date"), today=today)
    if start is None:
        raise ValueError(
            f"UNNORMALIZED_DATE: start_date {values.get('start_date')!r} is not a recognizable date"
        )
    end = normalize_trip_date(values.get("end_date"), today=today)
    if end is None:
        raise ValueError(
            f"UNNORMALIZED_DATE: end_date {values.get('end_date')!r} is not a recognizable date"
        )
    if end < start:
        raise ValueError("DATE_ORDER: end_date precedes start_date")
    if (end - start).days + 1 > 7:
        raise ValueError("TRIP_TOO_LONG: demo command supports at most 7 days")

    must_visit = values.get("must_visit")
    must_visit_places = (
        tuple(str(item) for item in must_visit) if isinstance(must_visit, list | tuple) else ()
    )
    pace = str(values.get("pace") or "").strip().upper()
    budget = _optional_decimal(values.get("budget"))

    constraints = TripConstraints(
        budgetAmount=budget,
        travelers=_optional_int(values.get("travelers"), default=1),
        travelerType="SOLO",
        pace=pace if pace in _PACES else "BALANCED",
        preferences=(),
        fixedSchedules=(),
        mealWindows=(),
        mustVisitPlaces=must_visit_places,
        schemaVersion=2,
    )
    snapshot = TripSnapshot(
        title=f"{destination} 的行程",
        destination=destination,
        startDate=start,
        endDate=end,
        status="DRAFT",
        version=0,
        constraints=constraints,
    )
    # The command is an in-process object here — pass the snapshot model
    # directly so null budget/constraint fields survive (a wire dump with
    # exclude_none would drop them and break re-validation).
    return PlanningCreateCommand(
        eventType="PLANNING_CREATE_REQUESTED",
        schemaVersion=2,
        eventId=uuid4(),
        traceId=uuid4(),
        taskId=uuid4(),
        tripId=UUID(trip_id) if trip_id else uuid4(),
        occurredAt=datetime.now(UTC),
        payload={
            "taskType": "CREATE",
            "baselineTripVersion": 0,
            "idempotencyKey": str(uuid4()),
            "trip": snapshot,
        },
    )


class DemoItineraryBuilder:
    """The no-key itinerary builder: slots → demo pipeline → itinerary."""

    def __init__(self, *, provider: DemoPlanningProvider | None = None) -> None:
        self._provider = provider or DemoPlanningProvider()

    async def __call__(
        self, *, slots: ConstraintSlots, trip_id: str | None = None
    ) -> Itinerary:
        command = build_demo_command(slots, trip_id=trip_id)
        result = await self._provider.plan(command)
        return result.itinerary


# ── V3 C-1: the real planning backend ───────────────────────────────────────


@runtime_checkable
class PlanningBackend(Protocol):
    """Structural protocol satisfied by both planning providers — the demo
    builder and the real AMap builder are interchangeable backends."""

    async def plan(self, command: PlanningCreateCommand) -> PlanningResult: ...


@dataclass(frozen=True, slots=True)
class BuiltItinerary:
    """The real backend's outcome: the itinerary plus its hard-validation
    summary.  The structural gate stays the EMITTED arbiter; this summary
    travels with the observation so the user and (C-3) the state can see it.
    """

    itinerary: Itinerary
    provider_name: str
    feasibility: dict[str, Any] | None = None
    # V3 C-3: the pipeline's own decision summaries (DecisionTrace) — the
    # agent's decision memory, capped to keep checkpoints small.
    decision_summaries: tuple[str, ...] = ()


class RealItineraryBuilder:
    """Slots → the deterministic planning pipeline (real provider) → a real
    itinerary with a hard-validation summary.

    The command projection is shared with the demo builder (same slots, same
    wire schema, same fail-closed normalization); only the backend differs.
    """

    def __init__(self, *, provider: PlanningBackend, provider_name: str = "AMAP") -> None:
        self._provider = provider
        self._provider_name = provider_name

    async def __call__(
        self, *, slots: ConstraintSlots, trip_id: str | None = None
    ) -> BuiltItinerary:
        command = build_demo_command(slots, trip_id=trip_id)
        result = await self._provider.plan(command)
        return BuiltItinerary(
            itinerary=result.itinerary,
            provider_name=self._provider_name,
            feasibility=_hard_validation_summary(command, result),
            decision_summaries=tuple(
                trace.summary for trace in result.decision_traces
            )[:12],
        )


def _hard_validation_summary(
    command: PlanningCreateCommand, result: PlanningResult
) -> dict[str, Any]:
    """Full hard validation (the same rules the worker enforces) as a compact
    summary dict — the agent's observation carries it; it never overrides the
    structural gate's EMITTED decision.

    E-1: for a hard-clean result (status != NEEDS_REPAIR) a ``quality``
    sub-structure is attached as feedback — deterministic, from the same
    ``PlanEvaluator`` the worker path uses, with zero new I/O.  Quality is
    feedback, never a failure (E-0 Fact C): it never enters ``failures``,
    never feeds the failure classifier, and never blocks emission."""
    run = run_validation(
        command=command,
        itinerary=result.itinerary,
        report_id=uuid5(command.task_id, "agent-itinerary-build"),
        validated_at=datetime.now(UTC),
        trip_skeleton=result.trip_skeleton,
        validation_inputs=result.validation_inputs,
    )
    report = run.report
    failures = [
        {
            "rule_id": result_rule.rule_id,
            "reason_code": result_rule.reason_code,
            "message": result_rule.message,
        }
        for result_rule in report.rule_results
        if result_rule.outcome.value == "FAIL"
    ]
    summary: dict[str, Any] = {"status": report.status.value, "failures": failures}
    if report.status.value != "NEEDS_REPAIR":
        quality = _quality_summary(command, result)
        if quality is not None:
            summary["quality"] = quality
    return summary


QUALITY_GOOD_AT = 80
QUALITY_POOR_AT = 60


def _quality_summary(
    command: PlanningCreateCommand, result: PlanningResult
) -> dict[str, Any] | None:
    """Deterministic quality feedback at the agent boundary (E-1 producer).

    Reuses the existing read-only ``PlanEvaluator`` (the same one the worker
    path calls at processor.py:280) — no new scorer, no new I/O.  Any
    evaluation failure (including ``PlanEvaluator`` raising on hard
    violations it can see but ``run_validation`` did not) degrades to
    ``None``: quality is feedback, fail-open; hard validation stays the
    fail-closed authority.
    """
    try:
        from trip_agent.evaluation import get_plan_evaluator

        evaluation = get_plan_evaluator().evaluate(command, result)
    except Exception:
        return None
    score = evaluation.overall_score
    verdict = (
        "GOOD"
        if score >= QUALITY_GOOD_AT
        else "ACCEPTABLE"
        if score >= QUALITY_POOR_AT
        else "POOR"
    )
    reasons = [warning.message for warning in evaluation.warnings[:3]]
    return {"verdict": verdict, "score": score, "reasons": reasons}
