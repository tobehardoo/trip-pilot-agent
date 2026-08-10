"""Stable hard-rule catalog for the standalone feasibility validator.

The catalog is the single source of truth for which hard rules exist
(REQUIRED_RULE_IDS) and which the current validator actually executes
(IMPLEMENTED_RULE_IDS).  Order is definitional and contract-level: it
is never derived from a set, so report ordering is stable across runs.
"""

from __future__ import annotations

from enum import StrEnum


class RuleId(StrEnum):
    """Every hard rule in the trip-planning domain, stable identifiers."""

    TRIP_DATE_RANGE = "TRIP_DATE_RANGE"
    FIXED_SCHEDULE_COVERAGE = "FIXED_SCHEDULE_COVERAGE"
    BUDGET_LIMIT = "BUDGET_LIMIT"
    MUST_VISIT_COVERAGE = "MUST_VISIT_COVERAGE"
    DUPLICATE_POI = "DUPLICATE_POI"
    ACTIVITY_OVERLAP = "ACTIVITY_OVERLAP"
    ROUTE_ENDPOINT_CONTINUITY = "ROUTE_ENDPOINT_CONTINUITY"
    CROSS_DAY_CONTINUITY = "CROSS_DAY_CONTINUITY"
    OPENING_HOURS = "OPENING_HOURS"
    VISIT_DURATION = "VISIT_DURATION"
    MEAL_WINDOW = "MEAL_WINDOW"


# Full contract set, in stable order.  The feasibility report lists results
# in this order and lists every unimplemented rule in missingRequiredRuleIds.
REQUIRED_RULE_IDS: tuple[str, ...] = tuple(member.value for member in RuleId)

# Rules the B4B hard validator actually executes.  A stable subset of
# REQUIRED_RULE_IDS; currently the five migrated runtime rules plus the two
# continuity rules.
IMPLEMENTED_RULE_IDS: tuple[str, ...] = (
    "TRIP_DATE_RANGE",
    "FIXED_SCHEDULE_COVERAGE",
    "BUDGET_LIMIT",
    "DUPLICATE_POI",
    "ACTIVITY_OVERLAP",
    "ROUTE_ENDPOINT_CONTINUITY",
    "CROSS_DAY_CONTINUITY",
)

# Rules required by the contract but not yet implemented; they remain in
# missingRequiredRuleIds until a future batch implements them.
MISSING_RULE_IDS: tuple[str, ...] = tuple(
    rule_id for rule_id in REQUIRED_RULE_IDS if rule_id not in IMPLEMENTED_RULE_IDS
)
