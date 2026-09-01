"""B2 RED 5 — legacy guard adapter contract.

``evaluation.rules.detect_hard_constraint_violations`` is the compatibility
bridge between the runtime guard and the canonical feasibility rules: it
must flatten findings into the exact legacy message texts, in the legacy
rule order (budget, date range, fixed schedules, duplicate POI, activity
overlap), preserve multiple findings per rule, return ``[]`` when nothing
violates, and never mutate the input itinerary.  Any divergence here would
break the evaluator's DATA_QUALITY_ERROR guard.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from plan_evaluation_support import make_activity, make_command, make_result

from trip_agent.evaluation.rules import detect_hard_constraint_violations
from trip_agent.feasibility.context import ValidationContext, build_budget_context
from trip_agent.feasibility.rules.core import (
    assess_activity_overlap,
    assess_budget_limit,
    assess_duplicate_poi,
    assess_fixed_schedule_coverage,
    assess_trip_date_range,
)
from trip_agent.worker.contracts import Itinerary, ItineraryDay


def _all_violations_scenario() -> tuple[object, Itinerary]:
    """Command + itinerary that violates all five implemented rules at once."""
    command = make_command(
        budget_amount=Decimal("1000.00"),
        fixed_schedules=(
            {
                "placeName": "Reserved dinner",
                "startTime": datetime(2026, 8, 1, 18, 0, tzinfo=UTC),
                "endTime": datetime(2026, 8, 1, 19, 0, tzinfo=UTC),
            },
        ),
    )
    first = make_activity(0, source="AMAP")  # 9:00-10:00, POI-1
    overlapping = make_activity(1, source="AMAP", start_hour=9, start_minute=30).model_copy(
        update={"provider_poi_id": first.provider_poi_id}  # repeat POI-1 -> DUPLICATE_POI
    )  # 9:30-10:30, overlaps with first
    itinerary = Itinerary(
        title="Broken",
        days=(
            ItineraryDay(
                date=date(2026, 8, 5),  # outside trip range 08-01..08-04
                activities=(first, overlapping),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("1100.00"),  # over the 1000.00 budget
    )
    return command, itinerary


# ── no violation ──────────────────────────────────────────────────────────


def test_bridge_returns_empty_list_when_nothing_violates() -> None:
    command = make_command()
    itinerary = make_result().itinerary  # within budget, in range, no overlaps

    violations = detect_hard_constraint_violations(
        command, itinerary, build_budget_context(command, itinerary)
    )

    assert violations == []


# ── legacy texts and order ────────────────────────────────────────────────


def test_bridge_reports_all_five_rules_in_legacy_order_with_old_texts() -> None:
    command, itinerary = _all_violations_scenario()

    violations = detect_hard_constraint_violations(
        command, itinerary, build_budget_context(command, itinerary)
    )

    assert violations == [
        "estimated cost exceeds budget by 10%",
        "day 2026-08-05 is outside trip range",
        "fixed schedule 'Reserved dinner' is not covered",
        "duplicate POI 'POI-1' appears more than once",
        "activities 'Activity 1' and 'Activity 2' overlap",
    ]


def test_bridge_flattens_multiple_findings_from_one_rule() -> None:
    command = make_command(
        fixed_schedules=(
            {
                "placeName": "Missing one",
                "startTime": datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
                "endTime": datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
            },
            {
                "placeName": "Missing two",
                "startTime": datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
                "endTime": datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
            },
        )
    )

    violations = detect_hard_constraint_violations(
        command,
        make_result().itinerary,
        build_budget_context(command, make_result().itinerary),
    )

    assert violations == [
        "fixed schedule 'Missing one' is not covered",
        "fixed schedule 'Missing two' is not covered",
    ]


# ── bridge vs canonical findings ──────────────────────────────────────────


def test_bridge_texts_match_canonical_findings_verbatim() -> None:
    """The bridge must be a pure flattening of the canonical rules — no
    second copy of judgement logic may drift."""
    command, itinerary = _all_violations_scenario()
    ctx = ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
    )
    canonical = [
        finding.message
        for assessment in (
            assess_budget_limit(ctx),
            assess_trip_date_range(ctx),
            assess_fixed_schedule_coverage(ctx),
            assess_duplicate_poi(ctx),
            assess_activity_overlap(ctx),
        )
        for finding in assessment.findings
    ]

    bridge = detect_hard_constraint_violations(
        command, itinerary, build_budget_context(command, itinerary)
    )

    assert bridge == canonical


def test_bridge_does_not_mutate_the_input_itinerary() -> None:
    command, itinerary = _all_violations_scenario()
    before = itinerary.model_dump_json(by_alias=True)

    detect_hard_constraint_violations(command, itinerary, build_budget_context(command, itinerary))

    assert itinerary.model_dump_json(by_alias=True) == before


def test_bridge_reports_nested_overlap_findings_in_detection_order() -> None:
    # A (09:00-12:00) contains B (10:00-10:30) and C (11:00-11:30): the
    # bridge must expose every overlapping pair, not just adjacent ones.
    command = make_command()
    outer_a = make_activity(0, title="A", start_hour=9, duration_minutes=180)
    inner_b = make_activity(1, title="B", start_hour=10, duration_minutes=30)
    inner_c = make_activity(2, title="C", start_hour=11, duration_minutes=30)
    itinerary = Itinerary(
        title="Nested",
        days=(
            ItineraryDay(
                date=date(2026, 8, 1),
                activities=(outer_a, inner_b, inner_c),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("100.00"),
    )

    violations = detect_hard_constraint_violations(
        command, itinerary, build_budget_context(command, itinerary)
    )

    assert violations == [
        "activities 'A' and 'B' overlap",
        "activities 'A' and 'C' overlap",
    ]


def test_bridge_flattens_oversized_duplicate_poi_findings_without_validation_error() -> None:
    # 65 distinct POIs each repeated once: the bridge must not blow up on
    # canonical aggregates capped at 64 refs; it must flatten all 65
    # duplicate findings verbatim alongside any other rule findings.
    command = make_command()
    activities: list = []
    for i in range(65):
        poi = f"P-{i:03d}"
        activities.append(
            make_activity(i, source="AMAP", start_hour=7 + (i % 8)).model_copy(
                update={"provider_poi_id": poi}
            )
        )
        activities.append(
            make_activity(65 + i, source="AMAP", start_hour=7 + (i % 8)).model_copy(
                update={"provider_poi_id": poi}
            )
        )
    itinerary = Itinerary(
        title="Many duplicates",
        days=(ItineraryDay(date=date(2026, 8, 1), activities=tuple(activities), transit_legs=()),),
        estimated_total_cost=Decimal("100.00"),
    )

    violations = detect_hard_constraint_violations(
        command, itinerary, build_budget_context(command, itinerary)
    )

    duplicate_violations = [
        violation for violation in violations if violation.startswith("duplicate POI")
    ]
    assert len(duplicate_violations) == 65
    assert "duplicate POI 'P-000' appears more than once" in duplicate_violations
    assert "duplicate POI 'P-064' appears more than once" in duplicate_violations
