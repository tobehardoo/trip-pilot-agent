"""Hard validator: executes the implemented canonical rules and aggregates a
FeasibilityReport through the B1 builder.

The validator is a pure function: everything it reads comes from the
command/itinerary pair, and the caller supplies ``report_id`` and
``validated_at`` so no clock or UUID entropy leaks into rule evaluation.
It never decides its own status — :func:`build_feasibility_report` derives
``status`` / ``summary`` / ``missing_required_rule_ids`` from the rule
outcomes and the required-rule set.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from trip_agent.feasibility.catalog import IMPLEMENTED_RULE_IDS, REQUIRED_RULE_IDS
from trip_agent.feasibility.context import ValidationContext, build_budget_context
from trip_agent.feasibility.fingerprint import compute_itinerary_fingerprint
from trip_agent.feasibility.models import FeasibilityReport, build_feasibility_report
from trip_agent.feasibility.rules.continuity import (
    assess_cross_day_continuity,
    assess_route_endpoint_continuity,
)
from trip_agent.feasibility.rules.core import (
    RuleAssessment,
    assess_activity_overlap,
    assess_budget_limit,
    assess_duplicate_poi,
    assess_fixed_schedule_coverage,
    assess_trip_date_range,
)
from trip_agent.feasibility.rules.coverage import assess_must_visit_coverage
from trip_agent.feasibility.rules.duration import assess_visit_duration
from trip_agent.feasibility.rules.meal import assess_meal_window
from trip_agent.feasibility.rules.opening import assess_opening_hours
from trip_agent.worker.contracts import (
    Itinerary,
    PlanningCreateCommand,
    PlanningReplanCommand,
)

if TYPE_CHECKING:
    from trip_agent.feasibility.inputs import ValidationInputs
    from trip_agent.planning.trip_skeleton import TripSkeleton

VALIDATOR_VERSION = "hard-validator-v3"

# Stable dispatch: rule_id -> canonical assessor, keyed by the catalog order
# so the report lists results in the same order as IMPLEMENTED_RULE_IDS.
# Every implemented rule must have an entry; the dispatch is never derived
# from a set.
_RULE_DISPATCH: dict[str, Callable[[ValidationContext], RuleAssessment]] = {
    "TRIP_DATE_RANGE": assess_trip_date_range,
    "FIXED_SCHEDULE_COVERAGE": assess_fixed_schedule_coverage,
    "BUDGET_LIMIT": assess_budget_limit,
    "MUST_VISIT_COVERAGE": assess_must_visit_coverage,
    "DUPLICATE_POI": assess_duplicate_poi,
    "ACTIVITY_OVERLAP": assess_activity_overlap,
    "ROUTE_ENDPOINT_CONTINUITY": assess_route_endpoint_continuity,
    "CROSS_DAY_CONTINUITY": assess_cross_day_continuity,
    "OPENING_HOURS": assess_opening_hours,
    "VISIT_DURATION": assess_visit_duration,
    "MEAL_WINDOW": assess_meal_window,
}


def validate_itinerary(
    command: PlanningCreateCommand | PlanningReplanCommand,
    itinerary: Itinerary,
    *,
    report_id: str | UUID,
    validated_at: datetime,
    trip_skeleton: TripSkeleton | None = None,
    validation_inputs: ValidationInputs | None = None,
) -> FeasibilityReport:
    """Run every implemented hard rule over the itinerary and aggregate the
    report.

    ``report_id`` and ``validated_at`` are caller-supplied to keep the
    validator deterministic.  ``trip_skeleton`` and ``validation_inputs``
    are transient planning aggregates; rules treat their absence as an
    evidence gap (UNKNOWN).  The report may be VERIFIED only when every
    required rule exists and no rule is FAIL or UNKNOWN.
    """
    ctx = ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
        trip_skeleton=trip_skeleton,
        validation_inputs=validation_inputs,
        validation_time=validated_at,
    )
    rule_results = tuple(
        _RULE_DISPATCH[rule_id](ctx).result for rule_id in IMPLEMENTED_RULE_IDS
    )
    return build_feasibility_report(
        report_id=report_id,
        validator_version=VALIDATOR_VERSION,
        itinerary_fingerprint=compute_itinerary_fingerprint(itinerary),
        validated_at=validated_at,
        required_rule_ids=REQUIRED_RULE_IDS,
        rule_results=rule_results,
    )
