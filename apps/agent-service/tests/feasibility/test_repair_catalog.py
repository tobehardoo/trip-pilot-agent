from __future__ import annotations

from trip_agent.feasibility.models import RuleOutcome
from trip_agent.feasibility.repair.catalog import (
    REPAIR_ACTION_SPECS,
    RepairActionCode,
    repair_action_for,
)


def test_repair_action_catalog_has_stable_supported_order() -> None:
    assert tuple(spec.code for spec in REPAIR_ACTION_SPECS) == (
        RepairActionCode.SHIFT_ACTIVITY_TO_OPENING_WINDOW,
        RepairActionCode.SHIFT_ACTIVITY_BEFORE_LAST_ENTRY,
        RepairActionCode.CLAMP_VISIT_DURATION,
        RepairActionCode.REMOVE_DUPLICATE_OPTIONAL_POI,
        RepairActionCode.REFRESH_TRANSIT_LEGS,
        RepairActionCode.SHIFT_MEAL_TO_WINDOW,
    )


def test_repair_action_catalog_maps_first_batch_reason_codes() -> None:
    cases = {
        (
            "OPENING_HOURS",
            "ACTIVITY_OUTSIDE_OPENING_WINDOW",
        ): RepairActionCode.SHIFT_ACTIVITY_TO_OPENING_WINDOW,
        (
            "OPENING_HOURS",
            "ACTIVITY_AFTER_LAST_ENTRY",
        ): RepairActionCode.SHIFT_ACTIVITY_BEFORE_LAST_ENTRY,
        ("VISIT_DURATION", "VISIT_TOO_SHORT"): RepairActionCode.CLAMP_VISIT_DURATION,
        ("VISIT_DURATION", "VISIT_TOO_LONG"): RepairActionCode.CLAMP_VISIT_DURATION,
        ("DUPLICATE_POI", "DUPLICATE_POI"): RepairActionCode.REMOVE_DUPLICATE_OPTIONAL_POI,
        ("ROUTE_ENDPOINT_CONTINUITY", "ROUTE_LEG_MISSING"): RepairActionCode.REFRESH_TRANSIT_LEGS,
        ("MEAL_WINDOW", "MEAL_OUTSIDE_WINDOW"): RepairActionCode.SHIFT_MEAL_TO_WINDOW,
    }

    for (rule_id, reason_code), expected in cases.items():
        spec = repair_action_for(rule_id, RuleOutcome.FAIL, reason_code)
        assert spec is not None
        assert spec.code is expected


def test_repair_action_catalog_rejects_non_fail_and_unsafe_failures() -> None:
    for outcome in (
        RuleOutcome.PASS,
        RuleOutcome.UNKNOWN,
        RuleOutcome.NOT_APPLICABLE,
    ):
        assert repair_action_for("VISIT_DURATION", outcome, "VISIT_TOO_LONG") is None

    for rule_id, reason_code in (
        ("OPENING_HOURS", "VENUE_CLOSED"),
        ("OPENING_HOURS", "OPENING_HOURS_UNVERIFIED"),
        ("MUST_VISIT_COVERAGE", "MUST_VISIT_PLACE_MISSING"),
        ("CROSS_DAY_CONTINUITY", "ACCOMMODATION_UNRESOLVED"),
        ("MEAL_WINDOW", "MEAL_PLACEMENT_MISSING"),
        ("BUDGET_LIMIT", "BUDGET_EXCEEDED"),
    ):
        assert repair_action_for(rule_id, RuleOutcome.FAIL, reason_code) is None
