"""Stable catalog of the first bounded repair actions.

Only an explicit FAIL mapping is repairable.  Missing bindings, unknown or
stale evidence, fixed schedules, must-visit requirements, accommodation and
budget failures intentionally have no entry: the repair engine must never
guess the data required to turn those outcomes into VERIFIED.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from trip_agent.feasibility.models import RuleOutcome


class RepairActionCode(StrEnum):
    SHIFT_ACTIVITY_TO_OPENING_WINDOW = "SHIFT_ACTIVITY_TO_OPENING_WINDOW"
    SHIFT_ACTIVITY_BEFORE_LAST_ENTRY = "SHIFT_ACTIVITY_BEFORE_LAST_ENTRY"
    CLAMP_VISIT_DURATION = "CLAMP_VISIT_DURATION"
    REMOVE_DUPLICATE_OPTIONAL_POI = "REMOVE_DUPLICATE_OPTIONAL_POI"
    REFRESH_TRANSIT_LEGS = "REFRESH_TRANSIT_LEGS"
    SHIFT_MEAL_TO_WINDOW = "SHIFT_MEAL_TO_WINDOW"


@dataclass(frozen=True, slots=True)
class RepairActionSpec:
    code: RepairActionCode
    rule_id: str
    reason_codes: tuple[str, ...]
    requires_provider: bool = False


REPAIR_ACTION_SPECS: tuple[RepairActionSpec, ...] = (
    RepairActionSpec(
        code=RepairActionCode.SHIFT_ACTIVITY_TO_OPENING_WINDOW,
        rule_id="OPENING_HOURS",
        reason_codes=("ACTIVITY_OUTSIDE_OPENING_WINDOW",),
    ),
    RepairActionSpec(
        code=RepairActionCode.SHIFT_ACTIVITY_BEFORE_LAST_ENTRY,
        rule_id="OPENING_HOURS",
        reason_codes=("ACTIVITY_AFTER_LAST_ENTRY",),
    ),
    RepairActionSpec(
        code=RepairActionCode.CLAMP_VISIT_DURATION,
        rule_id="VISIT_DURATION",
        reason_codes=("VISIT_TOO_SHORT", "VISIT_TOO_LONG"),
    ),
    RepairActionSpec(
        code=RepairActionCode.REMOVE_DUPLICATE_OPTIONAL_POI,
        rule_id="DUPLICATE_POI",
        reason_codes=("DUPLICATE_POI",),
    ),
    RepairActionSpec(
        code=RepairActionCode.REFRESH_TRANSIT_LEGS,
        rule_id="ROUTE_ENDPOINT_CONTINUITY",
        reason_codes=("ROUTE_LEG_MISSING",),
        requires_provider=True,
    ),
    RepairActionSpec(
        code=RepairActionCode.SHIFT_MEAL_TO_WINDOW,
        rule_id="MEAL_WINDOW",
        reason_codes=("MEAL_OUTSIDE_WINDOW",),
    ),
)


def repair_action_for(
    rule_id: str,
    outcome: RuleOutcome,
    reason_code: str,
) -> RepairActionSpec | None:
    """Return the explicit action for one aggregate rule outcome."""
    if outcome is not RuleOutcome.FAIL:
        return None
    return next(
        (
            spec
            for spec in REPAIR_ACTION_SPECS
            if spec.rule_id == rule_id and reason_code in spec.reason_codes
        ),
        None,
    )
