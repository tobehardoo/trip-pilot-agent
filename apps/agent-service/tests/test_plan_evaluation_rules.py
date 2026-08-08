from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from plan_evaluation_support import make_activity, make_command, make_result, make_transit

from trip_agent.evaluation.rules import (
    build_budget_context,
    compute_day_stats,
    daily_transfer_penalty,
    detect_hard_constraint_violations,
    score_budget_fit,
    score_time_feasibility,
    time_warnings,
    transfer_slack_minutes,
)
from trip_agent.worker.contracts import Itinerary, ItineraryDay


def test_budget_thresholds_are_monotonic_and_warn_at_eighty_five_percent() -> None:
    scores = []
    for cost in ("700.00", "850.00", "900.00", "1000.00"):
        result = make_result(estimated_total_cost=Decimal(cost))
        context = build_budget_context(make_command(), result.itinerary)
        scores.append(score_budget_fit(context))

    assert scores == [100, 90, 83, 70]


def test_critical_transfer_warning_reduces_the_time_score() -> None:
    activities = (
        make_activity(0),
        make_activity(1, start_hour=10, start_minute=4),
    )
    result = make_result(
        activities=activities,
        transit_legs=(make_transit(0, duration_seconds=180),),
    )
    stats = compute_day_stats(result.itinerary.days)

    warnings = time_warnings(result.itinerary.days, stats)

    # gap 4 min − transit 3 min → slack 1 min → CRITICAL −20 → 80
    assert score_time_feasibility(result.itinerary.days, stats) == 80
    assert [warning.code for warning in warnings] == ["TIGHT_TRANSFER", "LOW_TIME_BUFFER"]


def test_transfer_slack_subtracts_transit_duration() -> None:
    activities = (
        make_activity(0),
        make_activity(1, start_hour=10, start_minute=12),
    )
    result = make_result(
        activities=activities,
        transit_legs=(make_transit(0, duration_seconds=600),),
    )
    day = result.itinerary.days[0]

    assert transfer_slack_minutes(day, day.transit_legs[0]) == 2.0  # 12 − 10

    result_short = make_result(
        activities=activities,
        transit_legs=(make_transit(0, duration_seconds=180),),
    )
    short_day = result_short.itinerary.days[0]
    assert transfer_slack_minutes(short_day, short_day.transit_legs[0]) == 9.0  # 12 − 3


def test_critical_low_buffer_gets_extra_deduction() -> None:
    activities = (
        make_activity(0),
        make_activity(1, start_hour=10, start_minute=12),
    )
    result = make_result(
        activities=activities,
        transit_legs=(make_transit(0, duration_seconds=600),),
    )
    stats = compute_day_stats(result.itinerary.days)

    warnings = time_warnings(result.itinerary.days, stats)

    assert score_time_feasibility(result.itinerary.days, stats) == 80  # −15 − 5
    assert [warning.code for warning in warnings] == ["TIGHT_TRANSFER", "LOW_TIME_BUFFER"]


def test_tight_transfer_only_deduction() -> None:
    activities = (
        make_activity(0),
        make_activity(1, start_hour=10, start_minute=12),
    )
    result = make_result(
        activities=activities,
        transit_legs=(make_transit(0, duration_seconds=180),),
    )
    stats = compute_day_stats(result.itinerary.days)

    warnings = time_warnings(result.itinerary.days, stats)

    assert score_time_feasibility(result.itinerary.days, stats) == 85  # −15 only
    assert [warning.code for warning in warnings] == ["TIGHT_TRANSFER"]


def test_workload_penalty_is_progressive_and_capped() -> None:
    # Bands: 5.0–5.99 → −18; 6.0–6.99 → −24; >= 7.0 → −30 (capped per day).
    expectations = {5: 82, 6: 76, 7: 70, 9: 70}
    for count, expected in expectations.items():
        activities = tuple(
            make_activity(index, kind="ATTRACTION", start_hour=9 + index)
            for index in range(count)
        )
        result = make_result(activities=activities, transit_legs=())
        stats = compute_day_stats(result.itinerary.days)

        assert stats[0].workload == float(count)
        assert score_time_feasibility(result.itinerary.days, stats) == expected


def _combined_overload_day(activity_offset: int = 0) -> ItineraryDay:
    """One 5.5-workload day with exactly one tight leg (slack 9 min)."""
    kinds = (
        "ARRIVAL",
        "ATTRACTION",
        "ATTRACTION",
        "ATTRACTION",
        "ATTRACTION",
        "ATTRACTION",
        "MEAL",
        "ACCOMMODATION",
    )
    starts = (
        (9, 0), (10, 15), (11, 30), (12, 45), (14, 0), (15, 15), (16, 30), (17, 42),
    )
    activities = tuple(
        make_activity(
            activity_offset + index,
            kind=kind,
            start_hour=hour,
            start_minute=minute,
        )
        for index, (kind, (hour, minute)) in enumerate(zip(kinds, starts, strict=True))
    )
    legs = tuple(
        make_transit(index, duration_seconds=0 if index < 6 else 180)
        for index in range(7)
    )
    return ItineraryDay(
        date=date(2026, 8, 1),
        activities=activities,
        transit_legs=legs,
    )


def test_combined_high_load_and_tight_transfers_target_band() -> None:
    days = (_combined_overload_day(), _combined_overload_day(activity_offset=8))
    stats = compute_day_stats(days)

    assert stats[0].workload == 5.5
    assert stats[1].workload == 5.5

    # 2 days × −18 (workload) + 2 tight legs × −15 (slack 9) = −66 → 34
    assert score_time_feasibility(days, stats) == 34


def test_structural_anchors_do_not_count_as_full_workload() -> None:
    kinds = (
        "ARRIVAL",
        "ATTRACTION",
        "ATTRACTION",
        "ATTRACTION",
        "MEAL",
        "ATTRACTION",
        "DEPARTURE",
        "ACCOMMODATION",
    )
    activities = tuple(
        make_activity(index, kind=kind, start_hour=9 + index)
        for index, kind in enumerate(kinds)
    )
    result = make_result(activities=activities, transit_legs=())
    stats = compute_day_stats(result.itinerary.days)

    assert len(activities) == 8  # raw node count stays 8
    assert stats[0].activity_count == 8
    assert stats[0].workload == 4.5  # 4 attractions + 1 meal + 3 anchors at 0

    warnings = time_warnings(result.itinerary.days, stats)
    assert [warning.code for warning in warnings] == []
    assert score_time_feasibility(result.itinerary.days, stats) == 100


def test_demo_and_unknown_kind_count_as_full_workload() -> None:
    activities = tuple(
        make_activity(index, kind=None, start_hour=9 + index) for index in range(5)
    )
    result = make_result(activities=activities, transit_legs=())
    stats = compute_day_stats(result.itinerary.days)

    assert stats[0].activity_count == 5
    assert stats[0].workload == 5.0  # unknown kinds count as full activities

    warnings = time_warnings(result.itinerary.days, stats)
    assert [warning.code for warning in warnings] == ["HIGH_DAILY_LOAD"]


def test_hard_constraint_guard_reports_budget_date_and_appointment_violations() -> None:
    schedule = ({
        "placeName": "Reserved dinner",
        "startTime": datetime(2026, 8, 1, 18, 0, tzinfo=UTC),
        "endTime": datetime(2026, 8, 1, 19, 0, tzinfo=UTC),
    },)
    command = make_command(fixed_schedules=schedule)
    result = make_result(estimated_total_cost=Decimal("1100.00"))
    outside = result.itinerary.model_copy(
        update={
            "days": (
                result.itinerary.days[0].model_copy(
                    update={"date": result.itinerary.days[0].date.replace(day=5)}
                ),
            )
        }
    )

    violations = detect_hard_constraint_violations(
        command,
        outside,
        build_budget_context(command, outside),
    )

    assert violations == [
        "estimated cost exceeds budget by 10%",
        "day 2026-08-05 is outside trip range",
        "fixed schedule 'Reserved dinner' is not covered",
    ]


def test_fixed_schedule_requires_the_matching_place_not_only_the_time_window() -> None:
    schedule = ({
        "placeName": "Reserved museum",
        "startTime": datetime(2026, 8, 1, 9, 15, tzinfo=UTC),
        "endTime": datetime(2026, 8, 1, 9, 45, tzinfo=UTC),
    },)
    command = make_command(fixed_schedules=schedule)
    wrong_place = make_result(
        activities=(
            make_activity(0, title="Unrelated cafe"),
            make_activity(1),
        )
    )

    violations = detect_hard_constraint_violations(
        command,
        wrong_place.itinerary,
        build_budget_context(command, wrong_place.itinerary),
    )

    assert violations == ["fixed schedule 'Reserved museum' is not covered"]


def test_hard_constraint_guard_rejects_duplicate_poi_across_days() -> None:
    command = make_command()
    first = make_activity(0, source="AMAP")
    repeated = make_activity(1, source="AMAP").model_copy(
        update={"provider_poi_id": first.provider_poi_id}
    )
    itinerary = Itinerary(
        title="Duplicate trip",
        days=(
            ItineraryDay(
                date=command.payload.trip.start_date,
                activities=(first,),
                transit_legs=(),
            ),
            ItineraryDay(
                date=command.payload.trip.start_date.replace(day=2),
                activities=(repeated,),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("100.00"),
    )

    violations = detect_hard_constraint_violations(
        command,
        itinerary,
        build_budget_context(command, itinerary),
    )

    assert "duplicate POI 'POI-1' appears more than once" in violations


def test_hard_constraint_guard_rejects_overlapping_activities() -> None:
    command = make_command()
    first = make_activity(0)
    overlapping = make_activity(1, start_hour=9, start_minute=30)
    itinerary = Itinerary(
        title="Overlapping trip",
        days=(
            ItineraryDay(
                date=command.payload.trip.start_date,
                activities=(first, overlapping),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("100.00"),
    )

    violations = detect_hard_constraint_violations(
        command,
        itinerary,
        build_budget_context(command, itinerary),
    )

    assert "activities 'Activity 1' and 'Activity 2' overlap" in violations


# ── B1_C35: daily transfer penalty aggregation ─────────────────────────────

def _day_with_slacks(*slacks: int) -> ItineraryDay:
    """One day where leg i has exactly slacks[i] minutes of slack.

    Transit duration is fixed at 180 s (3 min), so the slack is precise:
    gap = slack + 3 minutes.
    """
    activities = [make_activity(0)]  # 9:00–10:00
    legs = []
    for index, slack in enumerate(slacks):
        previous_end = activities[-1].end_time
        start = previous_end + timedelta(minutes=slack + 3)
        activities.append(
            make_activity(index + 1, start_hour=start.hour, start_minute=start.minute)
        )
        legs.append(make_transit(index, duration_seconds=180))
    return ItineraryDay(
        date=date(2026, 8, 1),
        activities=tuple(activities),
        transit_legs=tuple(legs),
    )


def test_daily_transfer_penalty_single_tight_leg_is_fifteen() -> None:
    assert daily_transfer_penalty(_day_with_slacks(9)) == 15


def test_daily_transfer_penalty_single_critical_leg_is_twenty() -> None:
    assert daily_transfer_penalty(_day_with_slacks(0)) == 20


def test_daily_transfer_penalty_two_tight_legs_are_twenty() -> None:
    assert daily_transfer_penalty(_day_with_slacks(9, 9)) == 20


def test_daily_transfer_penalty_two_critical_legs_are_thirty() -> None:
    assert daily_transfer_penalty(_day_with_slacks(0, 0)) == 30


def test_daily_transfer_penalty_three_tight_legs_are_twenty_five() -> None:
    assert daily_transfer_penalty(_day_with_slacks(9, 9, 9)) == 25


def test_daily_transfer_penalty_three_critical_legs_are_capped_at_thirty_five() -> None:
    assert daily_transfer_penalty(_day_with_slacks(0, 0, 0)) == 35


def test_daily_transfer_penalty_six_tight_legs_are_capped_at_thirty_five() -> None:
    assert daily_transfer_penalty(_day_with_slacks(9, 9, 9, 9, 9, 9)) == 35


def test_daily_transfer_penalty_mixed_severities() -> None:
    assert daily_transfer_penalty(_day_with_slacks(9, 0)) == 25  # 1 T + 1 C
    assert daily_transfer_penalty(_day_with_slacks(9, 9, 0)) == 30  # 2 T + 1 C
    assert daily_transfer_penalty(_day_with_slacks(9, 0, 0)) == 35  # 1 T + 2 C


def test_daily_transfer_penalty_is_order_independent() -> None:
    # Same counts in different leg orders must yield identical penalties.
    assert daily_transfer_penalty(_day_with_slacks(9, 0)) == daily_transfer_penalty(
        _day_with_slacks(0, 9)
    )
    assert daily_transfer_penalty(_day_with_slacks(9, 9, 0)) == daily_transfer_penalty(
        _day_with_slacks(0, 9, 9)
    ) == daily_transfer_penalty(_day_with_slacks(9, 0, 9))
    assert daily_transfer_penalty(_day_with_slacks(9, 0, 0)) == daily_transfer_penalty(
        _day_with_slacks(0, 9, 0)
    ) == daily_transfer_penalty(_day_with_slacks(0, 0, 9))


def test_transfer_severity_boundaries() -> None:
    # slack == 12 → safe, no penalty (strict < 12).
    assert daily_transfer_penalty(_day_with_slacks(12)) == 0
    # slack just below 12 → TIGHT only.
    assert daily_transfer_penalty(_day_with_slacks(11)) == 15
    # slack == 4 → TIGHT only, not CRITICAL (strict < 4).
    assert daily_transfer_penalty(_day_with_slacks(4)) == 15
    # slack just below 4 → CRITICAL.
    assert daily_transfer_penalty(_day_with_slacks(3)) == 20


def test_time_score_integrates_daily_transfer_penalty() -> None:
    # 3 TIGHT legs in one day → −25 instead of the old linear −45.
    stats = compute_day_stats((_day_with_slacks(9, 9, 9),))
    assert score_time_feasibility((_day_with_slacks(9, 9, 9),), stats) == 75
    # 6 TIGHT legs → capped at −35, still not negative.
    assert daily_transfer_penalty(_day_with_slacks(9, 9, 9, 9, 9, 9)) == 35


def test_transfer_warnings_stay_per_leg_under_aggregation() -> None:
    # Aggregation caps the score but never merges or hides per-leg warnings:
    # every risk leg keeps its TIGHT_TRANSFER warning and critical legs
    # additionally keep LOW_TIME_BUFFER.
    day = _day_with_slacks(9, 9, 0)
    stats = compute_day_stats((day,))

    warnings = time_warnings((day,), stats)

    codes = [warning.code for warning in warnings]
    assert codes.count("TIGHT_TRANSFER") == 3
    assert codes.count("LOW_TIME_BUFFER") == 1
