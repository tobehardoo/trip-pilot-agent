"""P2.3: the feasibility gate lands on the real itinerary object.

The default gate checks structural integrity of the reconstructed
``Itinerary`` — pydantic reconstruction enforces the wire invariants (transit
legs adjacent and time-fitting, activities typed), the semantic checks here
cover what reconstruction cannot express.  This rule set is deliberately
narrower than the pipeline's Hard Validation suite; that parity lands with
the real-provider wiring, and the in-pipeline gate stays authoritative for
the Java command path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trip_agent.worker.contracts import Itinerary


@dataclass(frozen=True, slots=True)
class GateReport:
    """What ``validate_itinerary`` records as its observation payload."""

    has_blocker: bool
    violations: tuple[str, ...]
    summary: str


class StructuralFeasibilityGate:
    """Veto a candidate itinerary on structural integrity."""

    async def __call__(
        self, *, itinerary: dict[str, Any], slots: dict[str, Any]
    ) -> GateReport:
        del slots  # the veto object is the itinerary, not the slot map
        try:
            candidate = Itinerary.model_validate(itinerary)
        except ValueError as error:
            return GateReport(
                has_blocker=True,
                violations=(f"itinerary does not match the wire contract: {error}",),
                summary="feasibility gate: itinerary reconstruction failed",
            )
        violations: list[str] = []
        if not candidate.days:
            violations.append("itinerary has no days")
        for index, day in enumerate(candidate.days, start=1):
            if day.date < candidate.days[0].date:
                violations.append(f"day {index} predates the first day")
            for activity in day.activities:
                if activity.end_time <= activity.start_time:
                    violations.append(
                        f"day {index} activity {activity.title!r} ends before it starts"
                    )
        if violations:
            return GateReport(
                has_blocker=True,
                violations=tuple(violations),
                summary="feasibility gate: blocked",
            )
        return GateReport(
            has_blocker=False,
            violations=(),
            summary=(
                f"feasibility gate: passed ({len(candidate.days)} days, "
                f"{sum(len(day.activities) for day in candidate.days)} activities)"
            ),
        )
