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
from uuid import UUID

from trip_agent.feasibility.catalog import IMPLEMENTED_RULE_IDS, REQUIRED_RULE_IDS
from trip_agent.feasibility.context import ValidationContext, build_budget_context
from trip_agent.feasibility.fingerprint import compute_itinerary_fingerprint
from trip_agent.feasibility.models import FeasibilityReport, build_feasibility_report
from trip_agent.feasibility.rules.core import (
    RuleAssessment,
    assess_activity_overlap,
    assess_budget_limit,
    assess_duplicate_poi,
    assess_fixed_schedule_coverage,
    assess_trip_date_range,
)
from trip_agent.worker.contracts import (
    Itinerary,
    PlanningCreateCommand,
    PlanningReplanCommand,
)

VALIDATOR_VERSION = "hard-validator-v1"

# Stable dispatch: rule_id -> canonical assessor, keyed by the catalog order
# so the report lists results in the same order as IMPLEMENTED_RULE_IDS.
_RULE_DISPATCH: dict[str, Callable[[ValidationContext], RuleAssessment]] = {
    "TRIP_DATE_RANGE": assess_trip_date_range,
    "FIXED_SCHEDULE_COVERAGE": assess_fixed_schedule_coverage,
    "BUDGET_LIMIT": assess_budget_limit,
    "DUPLICATE_POI": assess_duplicate_poi,
    "ACTIVITY_OVERLAP": assess_activity_overlap,
}


def validate_itinerary(
    command: PlanningCreateCommand | PlanningReplanCommand,
    itinerary: Itinerary,
    *,
    report_id: str | UUID,
    validated_at: datetime,
) -> FeasibilityReport:
    """Run every implemented hard rule over the itinerary and aggregate the
    report.

    ``report_id`` and ``validated_at`` are caller-supplied to keep the
    validator deterministic.  The report's status is never VERIFIED while
    any required rule remains unimplemented (see the feasibility catalog).
    """
    ctx = ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
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
