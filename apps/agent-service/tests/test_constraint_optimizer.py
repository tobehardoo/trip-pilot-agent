from datetime import date, datetime, timedelta, timezone

from trip_agent.planning.optimization import DailyOptimizationRequest, DailyOptimizer, TimeBlock

CHINA_TIME_ZONE = timezone(timedelta(hours=8))


def local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, datetime.min.time(), CHINA_TIME_ZONE).replace(
        hour=hour, minute=minute
    )


def test_optimizer_reserves_route_time_and_avoids_a_fixed_schedule() -> None:
    day = date(2026, 7, 18)
    result = DailyOptimizer().optimize(
        DailyOptimizationRequest(
            date=day,
            visit_duration_minutes=120,
            route_duration_seconds=1_800,
            fixed_schedules=(
                TimeBlock("已预约午餐", local(day, 12), local(day, 13)),
            ),
        )
    )

    assert result.status == "FEASIBLE"
    assert result.first_start == local(day, 9)
    assert result.first_end == local(day, 11)
    assert result.second_start >= local(day, 13)
    assert result.second_start - result.first_end >= timedelta(minutes=30)
    assert result.second_end <= local(day, 18)


def test_optimizer_reports_overlapping_fixed_schedules_without_solving() -> None:
    day = date(2026, 7, 18)
    result = DailyOptimizer().optimize(
        DailyOptimizationRequest(
            date=day,
            fixed_schedules=(
                TimeBlock("预约 A", local(day, 10), local(day, 12)),
                TimeBlock("预约 B", local(day, 11), local(day, 13)),
            ),
        )
    )

    assert result.status == "INFEASIBLE"
    assert result.conflicts[0].code == "FIXED_SCHEDULE_OVERLAP"
    assert result.relaxations[0].code == "CHANGE_FIXED_SCHEDULE"


def test_optimizer_explains_when_the_day_has_insufficient_capacity() -> None:
    day = date(2026, 7, 18)
    result = DailyOptimizer().optimize(
        DailyOptimizationRequest(
            date=day,
            visit_duration_minutes=180,
            route_duration_seconds=7_200,
            fixed_schedules=(
                TimeBlock("整段预约", local(day, 9), local(day, 15)),
            ),
        )
    )

    assert result.status == "INFEASIBLE"
    assert result.conflicts[0].code == "INSUFFICIENT_DAY_CAPACITY"
    assert [item.code for item in result.relaxations] == [
        "REDUCE_OPTIONAL_ACTIVITIES",
        "EXTEND_AVAILABLE_TIME",
    ]
