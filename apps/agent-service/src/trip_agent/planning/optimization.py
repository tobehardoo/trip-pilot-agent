"""Bounded CP-SAT scheduling for a pair of daily POI visits."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import ceil
from typing import Literal

from ortools.sat.python import cp_model

CHINA_TIME_ZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
DAY_START_MINUTE = 9 * 60
DAY_END_MINUTE = 18 * 60


@dataclass(frozen=True, slots=True)
class TimeBlock:
    label: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("time block label must not be blank")
        if self.start.utcoffset() is None or self.end.utcoffset() is None:
            raise ValueError("time block timestamps must include a timezone")
        if self.end <= self.start:
            raise ValueError("time block end must be after start")


@dataclass(frozen=True, slots=True)
class OptimizationConflict:
    code: Literal[
        "FIXED_SCHEDULE_OVERLAP",
        "INSUFFICIENT_DAY_CAPACITY",
        "BUDGET_EXCEEDED",
        "MUST_VISIT_UNAVAILABLE",
        "MOBILITY_ROUTE_TOO_LONG",
    ]
    message: str
    affected: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelaxationSuggestion:
    code: Literal[
        "CHANGE_FIXED_SCHEDULE",
        "REDUCE_OPTIONAL_ACTIVITIES",
        "EXTEND_AVAILABLE_TIME",
        "INCREASE_BUDGET",
        "CHANGE_MOBILITY_OR_TRANSPORT",
    ]
    message: str


@dataclass(frozen=True, slots=True)
class DailyOptimizationRequest:
    date: date
    visit_duration_minutes: int = 120
    route_duration_seconds: int = 0
    fixed_schedules: tuple[TimeBlock, ...] = ()
    available_start_minute: int = DAY_START_MINUTE
    available_end_minute: int = DAY_END_MINUTE
    solve_timeout_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.visit_duration_minutes < 1:
            raise ValueError("visit duration must be positive")
        if self.route_duration_seconds < 0:
            raise ValueError("route duration must not be negative")
        if not 0 <= self.available_start_minute < self.available_end_minute <= 24 * 60:
            raise ValueError("available minutes must form a valid local-day range")
        if not 0 < self.solve_timeout_seconds <= 5:
            raise ValueError("solve timeout must be between zero and five seconds")


@dataclass(frozen=True, slots=True)
class DailyOptimizationResult:
    status: Literal["FEASIBLE", "INFEASIBLE"]
    first_start: datetime | None = None
    first_end: datetime | None = None
    second_start: datetime | None = None
    second_end: datetime | None = None
    conflicts: tuple[OptimizationConflict, ...] = ()
    relaxations: tuple[RelaxationSuggestion, ...] = ()
    optimal: bool = False


class DailyOptimizer:
    """Schedule two visits around immutable user time blocks."""

    def optimize(self, request: DailyOptimizationRequest) -> DailyOptimizationResult:
        fixed = _fixed_minutes(request)
        overlap = _overlapping_fixed(fixed)
        if overlap is not None:
            return DailyOptimizationResult(
                status="INFEASIBLE",
                conflicts=(OptimizationConflict(
                    "FIXED_SCHEDULE_OVERLAP",
                    "固定安排彼此重叠，无法构造一致的硬约束时间轴",
                    (overlap[0][0], overlap[1][0]),
                ),),
                relaxations=(RelaxationSuggestion(
                    "CHANGE_FIXED_SCHEDULE", "调整其中一个固定安排的开始或结束时间"
                ),),
            )

        duration = request.visit_duration_minutes
        route_minutes = ceil(request.route_duration_seconds / 60)
        day_start = request.available_start_minute
        day_end = request.available_end_minute
        if day_end - day_start < duration * 2 + route_minutes:
            return _capacity_failure(request, fixed)
        model = cp_model.CpModel()
        first_start = model.new_int_var(day_start, day_end - duration, "first")
        second_start = model.new_int_var(day_start, day_end - duration, "second")
        first_interval = model.new_fixed_size_interval_var(first_start, duration, "first_visit")
        second_interval = model.new_fixed_size_interval_var(second_start, duration, "second_visit")
        model.add(second_start >= first_start + duration + route_minutes)
        intervals: list[cp_model.IntervalVar] = [first_interval, second_interval]
        for index, (_, start_minute, end_minute) in enumerate(fixed):
            clipped_start = max(start_minute, day_start)
            clipped_end = min(end_minute, day_end)
            if clipped_start < clipped_end:
                intervals.append(
                    model.new_fixed_size_interval_var(
                        clipped_start, clipped_end - clipped_start, f"fixed_{index}"
                    )
                )
        model.add_no_overlap(intervals)
        preferred_second_delta = model.new_int_var(0, DAY_END_MINUTE, "second_delta")
        model.add_abs_equality(preferred_second_delta, second_start - 13 * 60)
        model.minimize((first_start - day_start) * 2 + preferred_second_delta)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = request.solve_timeout_seconds
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 0
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return _capacity_failure(request, fixed)
        first = solver.value(first_start)
        second = solver.value(second_start)
        return DailyOptimizationResult(
            status="FEASIBLE",
            first_start=_at_minute(request.date, first),
            first_end=_at_minute(request.date, first + duration),
            second_start=_at_minute(request.date, second),
            second_end=_at_minute(request.date, second + duration),
            optimal=status == cp_model.OPTIMAL,
        )


def _fixed_minutes(request: DailyOptimizationRequest) -> tuple[tuple[str, int, int], ...]:
    result = []
    for item in request.fixed_schedules:
        start = item.start.astimezone(CHINA_TIME_ZONE)
        end = item.end.astimezone(CHINA_TIME_ZONE)
        if start.date() != request.date and end.date() != request.date:
            continue
        start_minute = 0 if start.date() < request.date else start.hour * 60 + start.minute
        end_minute = 24 * 60 if end.date() > request.date else end.hour * 60 + end.minute
        result.append((item.label, start_minute, end_minute))
    return tuple(sorted(result, key=lambda item: (item[1], item[2], item[0])))


def _overlapping_fixed(
    fixed: tuple[tuple[str, int, int], ...],
) -> tuple[tuple[str, int, int], tuple[str, int, int]] | None:
    for previous, current in zip(fixed, fixed[1:], strict=False):
        if current[1] < previous[2]:
            return previous, current
    return None


def _capacity_failure(
    request: DailyOptimizationRequest,
    fixed: tuple[tuple[str, int, int], ...],
) -> DailyOptimizationResult:
    affected = tuple(item[0] for item in fixed) or (request.date.isoformat(),)
    return DailyOptimizationResult(
        status="INFEASIBLE",
        conflicts=(OptimizationConflict(
            "INSUFFICIENT_DAY_CAPACITY",
            "活动、交通与固定安排无法同时放入 09:00 至 18:00",
            affected,
        ),),
        relaxations=(
            RelaxationSuggestion("REDUCE_OPTIONAL_ACTIVITIES", "减少一个可选活动"),
            RelaxationSuggestion("EXTEND_AVAILABLE_TIME", "延长当日可用时间"),
        ),
    )


def _at_minute(day: date, minute: int) -> datetime:
    return datetime.combine(day, time.min, tzinfo=CHINA_TIME_ZONE) + timedelta(minutes=minute)
