"""Deterministic scoring rules and warning generators for PlanEvaluation.

All rules are side-effect-free functions that accept immutable inputs.
Thresholds and weights are centrally configured here — never scattered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from trip_agent.worker.contracts import (
    FallbackOperation,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    PlanningCreateCommand,
    TransitLeg,
)

# ── Central weight configuration ──────────────────────────────────────────

CONSTRAINT_SATISFACTION_WEIGHT = 0.30
TIME_FEASIBILITY_WEIGHT = 0.25
BUDGET_FIT_WEIGHT = 0.15
ROUTE_EFFICIENCY_WEIGHT = 0.15
INTEREST_MATCH_WEIGHT = 0.15

WEIGHTS = (
    ("constraintSatisfaction", CONSTRAINT_SATISFACTION_WEIGHT),
    ("timeFeasibility", TIME_FEASIBILITY_WEIGHT),
    ("budgetFit", BUDGET_FIT_WEIGHT),
    ("routeEfficiency", ROUTE_EFFICIENCY_WEIGHT),
    ("interestMatch", INTEREST_MATCH_WEIGHT),
)

# ── Threshold configuration ───────────────────────────────────────────────

# Budget: warning when estimated cost reaches this fraction of the budget.
BUDGET_WARNING_RATIO = 0.85  # >= 85% → warning, >= 100% → hard violation

# Walking leg thresholds (per leg)
SINGLE_WALK_DURATION_WARNING_SECONDS = 30 * 60  # 30 min
SINGLE_WALK_DISTANCE_WARNING_METERS = 2_000      # 2 km
DAILY_WALK_DURATION_WARNING_SECONDS = 60 * 60    # 1 hr

# Tight transfer: minimum buffer between activity end + transit → next start
MIN_BUFFER_MINUTES = 15  # < 15 min → tight transfer warning

# Daily load: too many activities or too much total time
HIGH_ACTIVITY_COUNT = 5          # >= 5 activities/day → warning
HIGH_DAILY_SPAN_HOURS = 12       # > 12 hours from first start to last end
HIGH_TOTAL_ROUTE_SECONDS = 3_600 # > 1 hr total transit in a day

# Late day end: activity ends after this local hour
LATE_DAY_END_HOUR = 20  # 8 PM


@dataclass(frozen=True, slots=True)
class BudgetContext:
    """Normalised budget data extracted once for all rules."""

    budget_amount: Decimal | None
    estimated_total_cost: Decimal
    budget_ratio: float | None  # None when budget not specified


@dataclass(frozen=True, slots=True)
class DayStats:
    """Per-day statistics computed once for all rules."""

    day_index: int
    activity_count: int
    first_activity_start: datetime | None
    last_activity_end: datetime | None
    span_hours: float | None
    total_route_seconds: int
    total_walk_seconds: int
    total_walk_meters: int
    activity_ids: tuple[UUID, ...]
    transit_ids: tuple[UUID, ...]


# ── Budget ─────────────────────────────────────────────────────────────────

def build_budget_context(
    command: PlanningCreateCommand, itinerary: Itinerary
) -> BudgetContext:
    budget_amount = command.payload.trip.constraints.budget_amount
    cost = itinerary.estimated_total_cost
    ratio = None
    if budget_amount is not None and budget_amount > 0:
        ratio = float(cost / budget_amount)
    return BudgetContext(
        budget_amount=budget_amount,
        estimated_total_cost=cost,
        budget_ratio=ratio,
    )


def score_budget_fit(ctx: BudgetContext) -> int:
    """Score budget utilisation.  Returns 0–100."""
    if ctx.budget_ratio is None:
        return 100  # no budget specified → no penalty
    if ctx.budget_ratio <= 0.70:
        return 100
    if ctx.budget_ratio <= 0.85:
        # Linear 100 → 90
        return round(100 - (ctx.budget_ratio - 0.70) / 0.15 * 10)
    if ctx.budget_ratio <= 1.0:
        # Linear 90 → 70
        return round(90 - (ctx.budget_ratio - 0.85) / 0.15 * 20)
    return 0  # over budget — should not reach completion


def budget_warning(ctx: BudgetContext) -> tuple[()] | tuple[object]:
    if ctx.budget_ratio is not None and ctx.budget_ratio >= BUDGET_WARNING_RATIO:
        from trip_agent.evaluation.models import EvaluationWarning

        return (EvaluationWarning(
            code="BUDGET_NEAR_LIMIT",
            severity="WARNING",
            message=f"预估费用已达到预算的 {round(ctx.budget_ratio * 100)}%",
            entity_type="PLAN",
            metric_key="budget_ratio",
            actual_value=round(ctx.budget_ratio, 3),
            threshold=BUDGET_WARNING_RATIO,
        ),)
    return ()


# ── Day statistics ─────────────────────────────────────────────────────────

def compute_day_stats(days: tuple[ItineraryDay, ...]) -> tuple[DayStats, ...]:
    result: list[DayStats] = []
    for day_index, day in enumerate(days):
        activities = day.activities
        transit_legs = day.transit_legs
        first_start = activities[0].start_time if activities else None
        last_end = activities[-1].end_time if activities else None
        span = None
        if first_start is not None and last_end is not None:
            span = (last_end - first_start).total_seconds() / 3600
        total_route = sum(leg.duration_seconds for leg in transit_legs)
        walk_legs = [leg for leg in transit_legs if leg.mode == "WALKING"]
        total_walk_seconds = sum(leg.duration_seconds for leg in walk_legs)
        total_walk_meters = sum(leg.distance_meters for leg in walk_legs)
        result.append(DayStats(
            day_index=day_index,
            activity_count=len(activities),
            first_activity_start=first_start,
            last_activity_end=last_end,
            span_hours=span,
            total_route_seconds=total_route,
            total_walk_seconds=total_walk_seconds,
            total_walk_meters=total_walk_meters,
            activity_ids=tuple(
                a.activity_id for a in activities if a.activity_id is not None
            ),
            transit_ids=tuple(
                t.transit_id for t in transit_legs if t.transit_id is not None
            ),
        ))
    return tuple(result)


# ── Time feasibility ───────────────────────────────────────────────────────

def score_time_feasibility(
    days: tuple[ItineraryDay, ...],
    day_stats: tuple[DayStats, ...],
) -> int:
    """Score temporal quality.  Starts at 100, deducts for issues."""
    score = 100
    for stats in day_stats:
        if stats.activity_count >= HIGH_ACTIVITY_COUNT:
            score -= 3
        if stats.span_hours is not None and stats.span_hours > HIGH_DAILY_SPAN_HOURS:
            score -= 5
        if stats.total_route_seconds > HIGH_TOTAL_ROUTE_SECONDS:
            score -= 3
    # Check tight transfers
    for day in days:
        for leg in day.transit_legs:
            from_end = day.activities[leg.from_activity_index].end_time
            to_start = day.activities[leg.to_activity_index].start_time
            buffer_min = (to_start - from_end).total_seconds() / 60
            if buffer_min < MIN_BUFFER_MINUTES:
                score -= 2
    return max(0, score)


def time_warnings(
    days: tuple[ItineraryDay, ...],
    day_stats: tuple[DayStats, ...],
) -> tuple[object, ...]:
    from trip_agent.evaluation.models import EvaluationWarning

    result: list[EvaluationWarning] = []
    for stats in day_stats:
        if stats.activity_count >= HIGH_ACTIVITY_COUNT:
            result.append(EvaluationWarning(
                code="HIGH_DAILY_LOAD",
                severity="WARNING",
                message=f"第 {stats.day_index + 1} 天有 {stats.activity_count} 个活动",
                day_index=stats.day_index,
                entity_type="DAY",
                metric_key="activity_count",
                actual_value=float(stats.activity_count),
                threshold=float(HIGH_ACTIVITY_COUNT),
            ))
        if stats.last_activity_end is not None:
            local_end = stats.last_activity_end.astimezone(
                stats.last_activity_end.tzinfo
            )
            if local_end.hour >= LATE_DAY_END_HOUR:
                result.append(EvaluationWarning(
                    code="LATE_DAY_END",
                    severity="INFO",
                    message=f"第 {stats.day_index + 1} 天结束时间较晚 ({local_end.strftime('%H:%M')})",
                    day_index=stats.day_index,
                    entity_type="DAY",
                    metric_key="last_activity_end_hour",
                    actual_value=float(local_end.hour),
                    threshold=float(LATE_DAY_END_HOUR),
                ))
    for day in days:
        for leg in day.transit_legs:
            from_end = day.activities[leg.from_activity_index].end_time
            to_start = day.activities[leg.to_activity_index].start_time
            buffer_min = (to_start - from_end).total_seconds() / 60
            if buffer_min < MIN_BUFFER_MINUTES:
                result.append(EvaluationWarning(
                    code="TIGHT_TRANSFER",
                    severity="WARNING",
                    message=f"活动间换乘时间仅 {round(buffer_min)} 分钟",
                    day_index=list(days).index(day),
                    entity_type="TRANSIT",
                    entity_id=leg.transit_id,
                    metric_key="buffer_minutes",
                    actual_value=round(buffer_min, 1),
                    threshold=float(MIN_BUFFER_MINUTES),
                ))
            if buffer_min < MIN_BUFFER_MINUTES / 3:
                result.append(EvaluationWarning(
                    code="LOW_TIME_BUFFER",
                    severity="CRITICAL",
                    message=f"活动间缓冲时间严重不足 ({round(buffer_min)} 分钟)",
                    day_index=list(days).index(day),
                    entity_type="TRANSIT",
                    entity_id=leg.transit_id,
                    metric_key="buffer_minutes",
                    actual_value=round(buffer_min, 1),
                    threshold=float(MIN_BUFFER_MINUTES / 3),
                ))
    return tuple(result)


# ── Route efficiency ───────────────────────────────────────────────────────

def score_route_efficiency(day_stats: tuple[DayStats, ...]) -> int:
    """Score route compactness.  Starts at 100, deducts for long transit."""
    score = 100
    for stats in day_stats:
        if stats.span_hours is not None and stats.span_hours > 0:
            route_ratio = stats.total_route_seconds / (stats.span_hours * 3600)
            if route_ratio > 0.4:
                score -= 10
            elif route_ratio > 0.25:
                score -= 5
    return max(0, score)


def route_warnings(days: tuple[ItineraryDay, ...]) -> tuple[object, ...]:
    from trip_agent.evaluation.models import EvaluationWarning

    result: list[EvaluationWarning] = []
    for day_idx, day in enumerate(days):
        for leg in day.transit_legs:
            if leg.mode == "WALKING":
                if leg.duration_seconds >= SINGLE_WALK_DURATION_WARNING_SECONDS:
                    result.append(EvaluationWarning(
                        code="LONG_WALKING",
                        severity="INFO",
                        message=f"步行路段较长 ({leg.duration_seconds // 60} 分钟, {leg.distance_meters}m)",
                        day_index=day_idx,
                        entity_type="TRANSIT",
                        entity_id=leg.transit_id,
                        metric_key="walk_duration_seconds",
                        actual_value=float(leg.duration_seconds),
                        threshold=float(SINGLE_WALK_DURATION_WARNING_SECONDS),
                    ))
                elif leg.distance_meters >= SINGLE_WALK_DISTANCE_WARNING_METERS:
                    result.append(EvaluationWarning(
                        code="LONG_WALKING",
                        severity="INFO",
                        message=f"步行距离较长 ({leg.distance_meters}m)",
                        day_index=day_idx,
                        entity_type="TRANSIT",
                        entity_id=leg.transit_id,
                        metric_key="walk_distance_meters",
                        actual_value=float(leg.distance_meters),
                        threshold=float(SINGLE_WALK_DISTANCE_WARNING_METERS),
                    ))
            if leg.estimated:
                result.append(EvaluationWarning(
                    code="ESTIMATED_TRANSIT",
                    severity="INFO",
                    message="此路段使用估算路线",
                    day_index=day_idx,
                    entity_type="TRANSIT",
                    entity_id=leg.transit_id,
                ))
    return tuple(result)


# ── Constraint satisfaction ────────────────────────────────────────────────

def score_constraint_satisfaction(
    command: PlanningCreateCommand,
    itinerary: Itinerary,
) -> int:
    """Score how well constraints are satisfied.  Start at 100, deduct for relaxations."""
    score = 100
    constraints = command.payload.trip.constraints
    # Must-visit places: check coverage
    must_visit = {n.strip().lower() for n in constraints.must_visit_places}
    if must_visit:
        visited = {
            a.title.strip().lower()
            for day in itinerary.days
            for a in day.activities
        }
        coverage = len(must_visit & visited) / len(must_visit)
        if coverage < 1.0:
            score -= round((1.0 - coverage) * 15)  # partial must-visit failure
    # Fixed schedules: check all are within activity time windows
    fixed_count = len(constraints.fixed_schedules)
    if fixed_count > 0:
        covered = 0
        for fs in constraints.fixed_schedules:
            for day in itinerary.days:
                for a in day.activities:
                    if a.start_time <= fs.start_time and a.end_time >= fs.end_time:
                        covered += 1
                        break
        if covered < fixed_count:
            score -= 5 * (fixed_count - covered)
    return max(0, score)


# ── Interest match ─────────────────────────────────────────────────────────

def score_interest_match(command: PlanningCreateCommand) -> int:
    """Score preference alignment at a basic level.

    NOTE: Full semantic interest matching requires reliable activity
    category tags which are not yet available in the domain model.
    This implementation provides a baseline coverage metric.
    """
    constraints = command.payload.trip.constraints
    pref_count = len(constraints.preferences)
    if pref_count == 0:
        return 100  # no explicit preferences → no penalty
    # With preferences set, reward is proportional to activity diversity
    # This is intentionally basic until rich activity tags are available.
    return 80  # baseline — acknowledges preferences exist without guessing


# ── Provider fallback warnings ─────────────────────────────────────────────

def provider_fallback_warnings(
    fallback_operations: tuple[FallbackOperation, ...],
) -> tuple[object, ...]:
    from trip_agent.evaluation.models import EvaluationWarning

    result: list[EvaluationWarning] = []
    for op in fallback_operations:
        result.append(EvaluationWarning(
            code="PROVIDER_FALLBACK_USED",
            severity="WARNING",
            message=f"路段使用 Demo 降级 ({op.error_category})",
            entity_type="TRANSIT",
            entity_id=op.transit_id,
            metric_key="fallback",
            actual_value=float(op.retry_count),
        ))
    return tuple(result)


# ── Constraint consistency guard ───────────────────────────────────────────

def detect_hard_constraint_violations(
    command: PlanningCreateCommand,
    itinerary: Itinerary,
    budget_ctx: BudgetContext,
) -> list[str]:
    """Detect hard-constraint violations that should block completion.

    Returns a list of violation descriptions.  An empty list means
    the result is safe to complete.
    """
    violations: list[str] = []
    constraints = command.payload.trip.constraints

    # Budget exceeded
    if budget_ctx.budget_ratio is not None and budget_ctx.budget_ratio > 1.0:
        violations.append(
            f"estimated cost exceeds budget by "
            f"{round((budget_ctx.budget_ratio - 1) * 100)}%"
        )

    # Trip date range
    trip_start = command.payload.trip.start_date
    trip_end = command.payload.trip.end_date
    for day in itinerary.days:
        if day.date < trip_start or day.date > trip_end:
            violations.append(f"day {day.date} is outside trip range")

    # Fixed schedules inside activity windows
    for fs in constraints.fixed_schedules:
        found = False
        for day in itinerary.days:
            for a in day.activities:
                if a.start_time <= fs.start_time and a.end_time >= fs.end_time:
                    found = True
                    break
        if not found:
            violations.append(f"fixed schedule '{fs.place_name}' is not covered")

    return violations
