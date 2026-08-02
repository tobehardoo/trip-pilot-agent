from datetime import UTC, datetime
from decimal import Decimal

from plan_evaluation_support import make_activity, make_command, make_result, make_transit

from trip_agent.evaluation.rules import (
    build_budget_context,
    compute_day_stats,
    detect_hard_constraint_violations,
    score_budget_fit,
    score_time_feasibility,
    time_warnings,
)


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

    assert score_time_feasibility(result.itinerary.days, stats) == 96
    assert [warning.code for warning in warnings] == ["TIGHT_TRANSFER", "LOW_TIME_BUFFER"]


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
