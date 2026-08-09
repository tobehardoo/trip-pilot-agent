"""B2 RED 3 — canonical hard-rule assessments.

Each rule is a pure function over ValidationContext producing exactly one
RuleResult plus immutable RuleFindings.  Old runtime texts must be
reproducible from the findings' messages so the legacy guard adapter can
flatten them without duplicating judgement logic.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from plan_evaluation_support import make_activity, make_command, make_result

from trip_agent.domain.shared import CHINA_TIME_ZONE
from trip_agent.feasibility.context import ValidationContext, build_budget_context
from trip_agent.feasibility.rules.core import (
    assess_activity_overlap,
    assess_budget_limit,
    assess_duplicate_poi,
    assess_fixed_schedule_coverage,
    assess_trip_date_range,
)
from trip_agent.worker.contracts import Itinerary, ItineraryDay


def _ctx(
    command: object | None = None,
    itinerary: Itinerary | None = None,
) -> ValidationContext:
    resolved_command = command or make_command()
    resolved_itinerary = itinerary or make_result().itinerary
    return ValidationContext(
        command=resolved_command,
        itinerary=resolved_itinerary,
        budget=build_budget_context(resolved_command, resolved_itinerary),
    )


def _two_day_itinerary(
    first_date: date,
    second_date: date,
    first_activities: tuple[object, ...],
    second_activities: tuple[object, ...],
) -> Itinerary:
    return Itinerary(
        title="Two-day itinerary",
        days=(
            ItineraryDay(date=first_date, activities=first_activities, transit_legs=()),
            ItineraryDay(date=second_date, activities=second_activities, transit_legs=()),
        ),
        estimated_total_cost=Decimal("200.00"),
    )


# ── TRIP_DATE_RANGE ──────────────────────────────────────────────────────


def test_trip_date_range_all_days_within_trip_passes() -> None:
    itinerary = _two_day_itinerary(
        date(2026, 8, 1), date(2026, 8, 2), (make_activity(0),), (make_activity(1),)
    )
    assessment = assess_trip_date_range(_ctx(itinerary=itinerary))

    assert assessment.result.rule_id == "TRIP_DATE_RANGE"
    assert assessment.result.outcome.value == "PASS"
    assert assessment.result.reason_code == "ALL_DAYS_WITHIN_TRIP_RANGE"
    assert assessment.result.affected_dates == ()
    assert assessment.findings == ()


def test_trip_date_range_rejects_a_single_outside_day() -> None:
    itinerary = _two_day_itinerary(
        date(2026, 8, 1), date(2026, 8, 5), (make_activity(0),), (make_activity(1),)
    )
    assessment = assess_trip_date_range(_ctx(itinerary=itinerary))

    assert assessment.result.outcome.value == "FAIL"
    assert assessment.result.reason_code == "DAY_OUTSIDE_TRIP_RANGE"
    assert assessment.result.affected_dates == (date(2026, 8, 5),)
    assert len(assessment.findings) == 1
    assert assessment.findings[0].message == "day 2026-08-05 is outside trip range"
    assert assessment.findings[0].affected_date == date(2026, 8, 5)


def test_trip_date_range_keeps_multiple_outside_days_as_multiple_findings() -> None:
    itinerary = _two_day_itinerary(
        date(2026, 7, 31), date(2026, 8, 9), (make_activity(0),), (make_activity(1),)
    )
    assessment = assess_trip_date_range(_ctx(itinerary=itinerary))

    assert assessment.result.outcome.value == "FAIL"
    assert assessment.result.affected_dates == (date(2026, 7, 31), date(2026, 8, 9))
    assert [finding.affected_date for finding in assessment.findings] == [
        date(2026, 7, 31),
        date(2026, 8, 9),
    ]


def test_trip_date_range_accepts_trip_boundaries_inclusive() -> None:
    itinerary = _two_day_itinerary(
        date(2026, 8, 1), date(2026, 8, 4), (make_activity(0),), (make_activity(1),)
    )
    assessment = assess_trip_date_range(_ctx(itinerary=itinerary))

    assert assessment.result.outcome.value == "PASS"


def test_trip_date_range_does_not_modify_the_input_itinerary() -> None:
    itinerary = make_result().itinerary
    before = itinerary.model_dump_json(by_alias=True)

    assess_trip_date_range(_ctx(itinerary=itinerary))

    assert itinerary.model_dump_json(by_alias=True) == before


# ── FIXED_SCHEDULE_COVERAGE ──────────────────────────────────────────────


def _schedule(
    place_name: str,
    start_hour: int = 9,
    start_minute: int = 0,
    end_hour: int = 10,
    end_minute: int = 0,
) -> dict[str, object]:
    return {
        "placeName": place_name,
        "startTime": datetime(2026, 8, 1, start_hour, start_minute, tzinfo=UTC),
        "endTime": datetime(2026, 8, 1, end_hour, end_minute, tzinfo=UTC),
    }


def test_fixed_schedule_coverage_is_not_applicable_without_schedules() -> None:
    assessment = assess_fixed_schedule_coverage(_ctx())

    assert assessment.result.rule_id == "FIXED_SCHEDULE_COVERAGE"
    assert assessment.result.outcome.value == "NOT_APPLICABLE"
    assert assessment.result.reason_code == "NO_FIXED_SCHEDULES"
    assert assessment.result.affected_dates == ()


def test_fixed_schedule_coverage_passes_when_every_schedule_is_covered() -> None:
    command = make_command(fixed_schedules=(_schedule("Reserved dinner"),))
    activity = make_activity(0, title="Reserved dinner", duration_minutes=120)
    itinerary = Itinerary(
        title="Covered",
        days=(ItineraryDay(date=date(2026, 8, 1), activities=(activity,), transit_legs=()),),
        estimated_total_cost=Decimal("100.00"),
    )
    assessment = assess_fixed_schedule_coverage(_ctx(command=command, itinerary=itinerary))

    assert assessment.result.outcome.value == "PASS"
    assert assessment.result.reason_code == "ALL_FIXED_SCHEDULES_COVERED"


def test_fixed_schedule_coverage_rejects_an_uncovered_schedule_with_old_text() -> None:
    command = make_command(fixed_schedules=(_schedule("Reserved museum"),))
    wrong_place = make_result(
        activities=(make_activity(0, title="Unrelated cafe"), make_activity(1))
    )
    assessment = assess_fixed_schedule_coverage(
        _ctx(command=command, itinerary=wrong_place.itinerary)
    )

    assert assessment.result.outcome.value == "FAIL"
    assert assessment.result.reason_code == "FIXED_SCHEDULE_NOT_COVERED"
    assert len(assessment.findings) == 1
    finding = assessment.findings[0]
    assert finding.message == "fixed schedule 'Reserved museum' is not covered"
    # affectedDates use the schedule's China-timezone date.
    assert (
        finding.affected_date
        == datetime(2026, 8, 1, 9, 0, tzinfo=UTC).astimezone(CHINA_TIME_ZONE).date()
    )


def test_fixed_schedule_coverage_keeps_one_finding_per_uncovered_schedule() -> None:
    command = make_command(
        fixed_schedules=(
            _schedule("Missing one"),
            _schedule("Missing two"),
        )
    )
    assessment = assess_fixed_schedule_coverage(_ctx(command=command))

    assert assessment.result.outcome.value == "FAIL"
    assert len(assessment.findings) == 2
    assert [finding.message for finding in assessment.findings] == [
        "fixed schedule 'Missing one' is not covered",
        "fixed schedule 'Missing two' is not covered",
    ]
    assert assessment.result.affected_dates == (date(2026, 8, 1),)


def test_fixed_schedule_matching_uses_normalised_place_name() -> None:
    # NFKC (fullwidth -> halfwidth) + casefold + alphanumeric-only comparison,
    # byte-for-byte the legacy normaliser.  (NFKC does not fold accented
    # letters like "é" into "e", so the test uses a true NFKC case.)
    command = make_command(
        fixed_schedules=({**_schedule("cafe no 1"), "placeName": "Ｃａｆｅ　Ｎｏ．１"},)
    )
    activity = make_activity(0, title="cafe no 1", duration_minutes=120)
    itinerary = Itinerary(
        title="Covered",
        days=(ItineraryDay(date=date(2026, 8, 1), activities=(activity,), transit_legs=()),),
        estimated_total_cost=Decimal("100.00"),
    )
    assessment = assess_fixed_schedule_coverage(_ctx(command=command, itinerary=itinerary))

    assert assessment.result.outcome.value == "PASS"


def test_fixed_schedule_matching_requires_full_time_window_cover() -> None:
    # Activity starts later than schedule start → not covered.
    command = make_command(fixed_schedules=(_schedule("Early window", start_hour=8),))
    activity = make_activity(0, title="Early window", start_hour=9, duration_minutes=120)
    itinerary = Itinerary(
        title="Late",
        days=(ItineraryDay(date=date(2026, 8, 1), activities=(activity,), transit_legs=()),),
        estimated_total_cost=Decimal("100.00"),
    )
    assessment = assess_fixed_schedule_coverage(_ctx(command=command, itinerary=itinerary))

    assert assessment.result.outcome.value == "FAIL"


# ── BUDGET_LIMIT ─────────────────────────────────────────────────────────


def test_budget_limit_is_not_applicable_without_budget() -> None:
    command = make_command(budget_amount=None)
    assessment = assess_budget_limit(_ctx(command=command))

    assert assessment.result.rule_id == "BUDGET_LIMIT"
    assert assessment.result.outcome.value == "NOT_APPLICABLE"
    assert assessment.result.reason_code == "BUDGET_NOT_SPECIFIED"


def test_budget_limit_passes_within_budget() -> None:
    assessment = assess_budget_limit(_ctx())

    assert assessment.result.outcome.value == "PASS"
    assert assessment.result.reason_code == "WITHIN_BUDGET"


def test_budget_limit_passes_at_exactly_one_hundred_percent() -> None:
    command = make_command(budget_amount=Decimal("500.00"))
    assessment = assess_budget_limit(
        _ctx(
            command=command,
            itinerary=make_result(estimated_total_cost=Decimal("500.00")).itinerary,
        )
    )

    assert assessment.result.outcome.value == "PASS"


def test_budget_limit_fails_over_budget_with_old_text() -> None:
    command = make_command(budget_amount=Decimal("1000.00"))
    itinerary = make_result(estimated_total_cost=Decimal("1100.00")).itinerary
    assessment = assess_budget_limit(_ctx(command=command, itinerary=itinerary))

    assert assessment.result.outcome.value == "FAIL"
    assert assessment.result.reason_code == "BUDGET_EXCEEDED"
    assert len(assessment.findings) == 1
    assert assessment.findings[0].message == "estimated cost exceeds budget by 10%"


def test_budget_limit_rounding_matches_legacy_text() -> None:
    command = make_command(budget_amount=Decimal("1000.00"))
    itinerary = make_result(estimated_total_cost=Decimal("1234.50")).itinerary
    assessment = assess_budget_limit(_ctx(command=command, itinerary=itinerary))

    assert assessment.findings[0].message == "estimated cost exceeds budget by 23%"


# ── DUPLICATE_POI ────────────────────────────────────────────────────────


def test_duplicate_poi_passes_with_unique_attractions() -> None:
    itinerary = _two_day_itinerary(
        date(2026, 8, 1),
        date(2026, 8, 2),
        (make_activity(0, source="AMAP"),),
        (make_activity(1, source="AMAP"),),
    )
    assessment = assess_duplicate_poi(_ctx(itinerary=itinerary))

    assert assessment.result.rule_id == "DUPLICATE_POI"
    assert assessment.result.outcome.value == "PASS"
    assert assessment.result.reason_code == "NO_DUPLICATE_POI"


def test_duplicate_poi_fails_with_repeated_attraction_across_days() -> None:
    first = make_activity(0, source="AMAP")
    repeated = make_activity(1, source="AMAP").model_copy(
        update={"provider_poi_id": first.provider_poi_id}
    )
    itinerary = _two_day_itinerary(date(2026, 8, 1), date(2026, 8, 2), (first,), (repeated,))
    assessment = assess_duplicate_poi(_ctx(itinerary=itinerary))

    assert assessment.result.outcome.value == "FAIL"
    assert assessment.result.reason_code == "DUPLICATE_POI"
    assert len(assessment.findings) == 1
    assert (
        assessment.findings[0].message
        == f"duplicate POI '{first.provider_poi_id}' appears more than once"
    )
    assert assessment.result.affected_dates == (date(2026, 8, 2),)
    assert assessment.result.affected_entity_refs == (first.provider_poi_id,)


def test_duplicate_poi_ignores_none_provider_poi_ids() -> None:
    first = make_activity(0, source="DEMO")  # provider_poi_id is None
    repeated = make_activity(1, source="DEMO")
    itinerary = _two_day_itinerary(date(2026, 8, 1), date(2026, 8, 2), (first,), (repeated,))
    assessment = assess_duplicate_poi(_ctx(itinerary=itinerary))

    assert assessment.result.outcome.value == "PASS"


@pytest.mark.parametrize(
    "kind",
    ["ACCOMMODATION", "ARRIVAL", "DEPARTURE", "MEAL"],
)
def test_duplicate_poi_allows_structural_kind_repeats(kind: str) -> None:
    first = make_activity(0, source="AMAP", kind=kind)
    repeated = make_activity(1, source="AMAP", kind=kind).model_copy(
        update={"provider_poi_id": first.provider_poi_id}
    )
    itinerary = _two_day_itinerary(date(2026, 8, 1), date(2026, 8, 2), (first,), (repeated,))
    assessment = assess_duplicate_poi(_ctx(itinerary=itinerary))

    assert assessment.result.outcome.value == "PASS"


def test_duplicate_poi_keeps_one_finding_per_repeat_and_stable_order() -> None:
    first = make_activity(0, source="AMAP")
    repeat_two = make_activity(1, source="AMAP").model_copy(
        update={"provider_poi_id": first.provider_poi_id}
    )
    repeat_three = make_activity(2, source="AMAP").model_copy(
        update={"provider_poi_id": first.provider_poi_id}
    )
    itinerary = Itinerary(
        title="Triple",
        days=(
            ItineraryDay(
                date=date(2026, 8, 1), activities=(first, repeat_two, repeat_three), transit_legs=()
            ),
        ),
        estimated_total_cost=Decimal("300.00"),
    )
    assessment = assess_duplicate_poi(_ctx(itinerary=itinerary))

    assert assessment.result.outcome.value == "FAIL"
    assert len(assessment.findings) == 2
    assert all(
        finding.message == f"duplicate POI '{first.provider_poi_id}' appears more than once"
        for finding in assessment.findings
    )
    assert assessment.result.affected_entity_refs == (first.provider_poi_id,)


# ── ACTIVITY_OVERLAP ─────────────────────────────────────────────────────


def test_activity_overlap_passes_with_sequential_activities() -> None:
    assessment = assess_activity_overlap(_ctx())

    assert assessment.result.rule_id == "ACTIVITY_OVERLAP"
    assert assessment.result.outcome.value == "PASS"
    assert assessment.result.reason_code == "NO_ACTIVITY_OVERLAP"


def test_activity_overlap_fails_with_overlapping_activities_and_old_text() -> None:
    first = make_activity(0)
    overlapping = make_activity(1, start_hour=9, start_minute=30)
    itinerary = Itinerary(
        title="Overlapping",
        days=(
            ItineraryDay(date=date(2026, 8, 1), activities=(first, overlapping), transit_legs=()),
        ),
        estimated_total_cost=Decimal("100.00"),
    )
    assessment = assess_activity_overlap(_ctx(itinerary=itinerary))

    assert assessment.result.outcome.value == "FAIL"
    assert assessment.result.reason_code == "ACTIVITY_OVERLAP"
    assert len(assessment.findings) == 1
    assert assessment.findings[0].message == "activities 'Activity 1' and 'Activity 2' overlap"
    assert assessment.findings[0].affected_date == date(2026, 8, 1)


def test_activity_overlap_adjacent_boundaries_do_not_overlap() -> None:
    first = make_activity(0, duration_minutes=60)  # 9:00-10:00
    adjacent = make_activity(1, start_hour=10)  # 10:00-11:00
    itinerary = Itinerary(
        title="Adjacent",
        days=(ItineraryDay(date=date(2026, 8, 1), activities=(first, adjacent), transit_legs=()),),
        estimated_total_cost=Decimal("100.00"),
    )
    assessment = assess_activity_overlap(_ctx(itinerary=itinerary))

    assert assessment.result.outcome.value == "PASS"


def test_activity_overlap_aggregates_findings_across_days() -> None:
    overlapping_a = make_activity(0, start_hour=9, start_minute=30)
    first_a = make_activity(1, start_hour=9)
    overlapping_b = make_activity(2, start_hour=15, start_minute=15)
    first_b = make_activity(3, start_hour=15)
    itinerary = _two_day_itinerary(
        date(2026, 8, 1),
        date(2026, 8, 2),
        (first_a, overlapping_a),
        (first_b, overlapping_b),
    )
    assessment = assess_activity_overlap(_ctx(itinerary=itinerary))

    assert assessment.result.outcome.value == "FAIL"
    assert len(assessment.findings) == 2
    assert assessment.result.affected_dates == (date(2026, 8, 1), date(2026, 8, 2))


def test_activity_overlap_is_order_stable_for_detection() -> None:
    # The rule must sort by (start, end) before comparing, so input order
    # does not change the finding.
    first = make_activity(0, start_hour=9)
    later = make_activity(1, start_hour=9, start_minute=30)
    ordered = Itinerary(
        title="Ordered",
        days=(ItineraryDay(date=date(2026, 8, 1), activities=(first, later), transit_legs=()),),
        estimated_total_cost=Decimal("100.00"),
    )
    shuffled = Itinerary(
        title="Shuffled",
        days=(ItineraryDay(date=date(2026, 8, 1), activities=(later, first), transit_legs=()),),
        estimated_total_cost=Decimal("100.00"),
    )

    ordered_assessment = assess_activity_overlap(_ctx(itinerary=ordered))
    shuffled_assessment = assess_activity_overlap(_ctx(itinerary=shuffled))

    assert ordered_assessment.result.outcome.value == "FAIL"
    assert [f.message for f in ordered_assessment.findings] == [
        f.message for f in shuffled_assessment.findings
    ]


def test_activity_overlap_detects_nested_intervals() -> None:
    # A (09:00-12:00) contains B (10:00-10:30) and C (11:00-11:30).
    # B and C do not overlap each other, but both overlap A.  Adjacent-pair
    # scanning misses the A/C finding.
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

    assessment = assess_activity_overlap(_ctx(itinerary=itinerary))

    assert assessment.result.outcome.value == "FAIL"
    assert [finding.message for finding in assessment.findings] == [
        "activities 'A' and 'B' overlap",
        "activities 'A' and 'C' overlap",
    ]


def test_activity_overlap_detects_chained_nested_intervals() -> None:
    # A (09:00-12:00) contains B (10:00-11:30); C (11:00-12:30) overlaps
    # both A and B.  Adjacent-pair scanning misses the A/C finding.
    outer_a = make_activity(0, title="A", start_hour=9, duration_minutes=180)
    mid_b = make_activity(1, title="B", start_hour=10, duration_minutes=90)
    tail_c = make_activity(2, title="C", start_hour=11, duration_minutes=90)
    itinerary = Itinerary(
        title="Chained",
        days=(
            ItineraryDay(
                date=date(2026, 8, 1),
                activities=(outer_a, mid_b, tail_c),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("100.00"),
    )

    assessment = assess_activity_overlap(_ctx(itinerary=itinerary))

    assert assessment.result.outcome.value == "FAIL"
    assert [finding.message for finding in assessment.findings] == [
        "activities 'A' and 'B' overlap",
        "activities 'A' and 'C' overlap",
        "activities 'B' and 'C' overlap",
    ]


def test_duplicate_poi_bounds_aggregate_refs_at_64() -> None:
    # 65 distinct POIs, each repeated once: 65 findings but the aggregate
    # refs must be capped at 64, deduplicated and lexicographically stable.
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

    assessment = assess_duplicate_poi(_ctx(itinerary=itinerary))

    assert assessment.result.outcome.value == "FAIL"
    assert len(assessment.findings) == 65
    assert len(assessment.result.affected_entity_refs) == 64
    assert assessment.result.affected_entity_refs == tuple(f"P-{i:03d}" for i in range(64))


def test_duplicate_poi_public_refs_are_input_order_stable() -> None:
    def build(activities: tuple) -> Itinerary:
        return Itinerary(
            title="Many duplicates",
            days=(ItineraryDay(date=date(2026, 8, 1), activities=activities, transit_legs=()),),
            estimated_total_cost=Decimal("100.00"),
        )

    forward: list = []
    for i in range(65):
        poi = f"P-{i:03d}"
        forward.append(
            make_activity(i, source="AMAP", start_hour=7 + (i % 8)).model_copy(
                update={"provider_poi_id": poi}
            )
        )
        forward.append(
            make_activity(65 + i, source="AMAP", start_hour=7 + (i % 8)).model_copy(
                update={"provider_poi_id": poi}
            )
        )

    forward_assessment = assess_duplicate_poi(_ctx(itinerary=build(tuple(forward))))
    backward_assessment = assess_duplicate_poi(_ctx(itinerary=build(tuple(reversed(forward)))))

    assert forward_assessment.result.affected_entity_refs == (
        backward_assessment.result.affected_entity_refs
    )
    assert forward_assessment.result.affected_entity_refs == tuple(f"P-{i:03d}" for i in range(64))


def test_trip_date_range_bounds_aggregate_dates_at_16() -> None:
    # 17 out-of-range days produce 17 findings but the aggregate dates must
    # be capped at 16, deduplicated and ascending.
    days = tuple(
        ItineraryDay(
            date=date(2026, 8, 5) + timedelta(days=i),
            activities=(make_activity(0),),
            transit_legs=(),
        )
        for i in range(17)
    )
    itinerary = Itinerary(
        title="Outside range",
        days=days,
        estimated_total_cost=Decimal("100.00"),
    )

    assessment = assess_trip_date_range(_ctx(itinerary=itinerary))

    assert assessment.result.outcome.value == "FAIL"
    assert len(assessment.findings) == 17
    assert len(assessment.result.affected_dates) == 16
    assert assessment.result.affected_dates == tuple(
        date(2026, 8, 5) + timedelta(days=i) for i in range(16)
    )
