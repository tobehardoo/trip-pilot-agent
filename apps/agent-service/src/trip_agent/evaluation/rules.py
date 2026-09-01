"""Deterministic scoring rules and warning generators for PlanEvaluation.

All rules are side-effect-free functions that accept immutable inputs.
Thresholds and weights are centrally configured here — never scattered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from trip_agent.feasibility.context import (
    BudgetContext,
    ValidationContext,
)
from trip_agent.feasibility.rules.core import (
    activity_covers_fixed_schedule,
    assess_activity_overlap,
    assess_budget_limit,
    assess_duplicate_poi,
    assess_fixed_schedule_coverage,
    assess_trip_date_range,
)
from trip_agent.worker.contracts import (
    FallbackOperation,
    Itinerary,
    ItineraryDay,
    PlanningCandidateValidationCommand,
    PlanningCreateCommand,
    PlanningReplanCommand,
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
# Approved 2026-08-08: thresholds are based on *actual slack* (gap − transit
# duration), not the raw gap. 12 and 4 are independent constants (no 1/3 rule).
TIGHT_TRANSFER_SLACK_MINUTES = 12.0  # slack < 12 min → TIGHT_TRANSFER warning
LOW_BUFFER_SLACK_MINUTES = 4.0       # slack < 4 min → LOW_TIME_BUFFER critical

# Transfer penalty accumulation (B1_C35): within a day, the first risk leg
# carries its full deduction, every further risk leg adds a reduced amount,
# and the daily total is capped.  Classification is mutually exclusive:
# a slack < 4 min leg counts only as critical, never also as tight.
FIRST_RISK_LEG_EXTRA_PENALTY = 10  # full − reduced for both severities
TIGHT_ONLY_ADDITIONAL_PENALTY = 5  # per further TIGHT-only leg
CRITICAL_ADDITIONAL_PENALTY = 10   # per further CRITICAL leg
DAILY_TRANSFER_PENALTY_CAP = 35    # daily score saturation bound

# Daily load: weighted activity workload (anchors weightless, meals light).
# Unknown kinds (None) count as full activities to prevent gaming.
ACTIVITY_KIND_WORKLOAD: dict[str, float] = {
    "ATTRACTION": 1.0,
    "EXPERIENCE": 1.0,
    "MEAL": 0.5,            # meal occupies time but carries light load
    "ACCOMMODATION": 0.0,   # overnight node, no daytime load
    "ARRIVAL": 0.0,         # arrival buffer
    "DEPARTURE": 0.0,       # departure buffer
}
HIGH_DAILY_WORKLOAD = 5.0  # weighted workload >= 5.0 → HIGH_DAILY_LOAD
HIGH_DAILY_SPAN_HOURS = 12       # > 12 hours from first start to last end
HIGH_TOTAL_ROUTE_SECONDS = 3_600 # > 1 hr total transit in a day

# Late day end: activity ends after this local hour
LATE_DAY_END_HOUR = 20  # 8 PM


@dataclass(frozen=True, slots=True)
class DayStats:
    """Per-day statistics computed once for all rules."""

    day_index: int
    activity_count: int
    workload: float
    first_activity_start: datetime | None
    last_activity_end: datetime | None
    span_hours: float | None
    total_route_seconds: int
    total_walk_seconds: int
    total_walk_meters: int
    activity_ids: tuple[UUID, ...]
    transit_ids: tuple[UUID, ...]


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
        workload = sum(
            ACTIVITY_KIND_WORKLOAD.get(activity.kind, 1.0) for activity in activities
        )
        result.append(DayStats(
            day_index=day_index,
            activity_count=len(activities),
            workload=workload,
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

def transfer_slack_minutes(day: ItineraryDay, leg: TransitLeg) -> float:
    """Actual transfer margin in minutes: gap − transit duration.

    Single source of truth shared by the warning classifier and the score
    function so the two can never drift apart.
    """
    from_end = day.activities[leg.from_activity_index].end_time
    to_start = day.activities[leg.to_activity_index].start_time
    gap_min = (to_start - from_end).total_seconds() / 60
    return gap_min - leg.duration_seconds / 60


def daily_transfer_penalty(day: ItineraryDay) -> int:
    """B1_C35 daily transfer penalty for one day, 0..35.

    Counts risk legs with mutually exclusive severity (a slack < 4 min leg
    is CRITICAL and is never also counted as TIGHT-only):

        tight_only_count = legs with 4 <= slack < 12
        critical_count    = legs with slack < 4

    raw = 10 + 5 * tight_only_count + 10 * critical_count  (when any risk)
    daily = min(raw, 35)

    The formula depends only on the counts, never on TransitLeg order:
    1 TIGHT = 15, 2 TIGHT = 20, 3 TIGHT = 25, 4 TIGHT = 30, 5+ TIGHT = 35;
    1 CRITICAL = 20, 2 CRITICAL = 30, 3+ CRITICAL = 35;
    1 TIGHT + 1 CRITICAL = 25, 2 TIGHT + 1 CRITICAL = 30,
    1 TIGHT + 2 CRITICAL = 35.
    """
    tight_only_count = 0
    critical_count = 0
    for leg in day.transit_legs:
        slack = transfer_slack_minutes(day, leg)
        if slack < LOW_BUFFER_SLACK_MINUTES:
            critical_count += 1
        elif slack < TIGHT_TRANSFER_SLACK_MINUTES:
            tight_only_count += 1
    if tight_only_count == 0 and critical_count == 0:
        return 0
    raw = (
        FIRST_RISK_LEG_EXTRA_PENALTY
        + TIGHT_ONLY_ADDITIONAL_PENALTY * tight_only_count
        + CRITICAL_ADDITIONAL_PENALTY * critical_count
    )
    return min(raw, DAILY_TRANSFER_PENALTY_CAP)


def score_time_feasibility(
    days: tuple[ItineraryDay, ...],
    day_stats: tuple[DayStats, ...],
) -> int:
    """Score temporal quality.  Starts at 100, deducts for issues."""
    score = 100
    for stats in day_stats:
        # Progressive daily-load penalty: −18 base, +6 per full workload tier,
        # capped at −30 per day.  Bands: 5.0–5.99 → −18; 6.0–6.99 → −24; ≥7.0 → −30.
        overload = stats.workload - HIGH_DAILY_WORKLOAD
        if overload >= 0:
            score -= min(18 + 6 * int(overload), 30)
        if stats.span_hours is not None and stats.span_hours > HIGH_DAILY_SPAN_HOURS:
            score -= 5
        if stats.total_route_seconds > HIGH_TOTAL_ROUTE_SECONDS:
            score -= 3
    # Check tight transfers against the shared actual-slack signal,
    # accumulated per day (B1_C35) with a daily cap.
    for day in days:
        score -= daily_transfer_penalty(day)
    return max(0, score)


def time_warnings(
    days: tuple[ItineraryDay, ...],
    day_stats: tuple[DayStats, ...],
) -> tuple[object, ...]:
    from trip_agent.evaluation.models import EvaluationWarning

    result: list[EvaluationWarning] = []
    for stats in day_stats:
        if stats.workload >= HIGH_DAILY_WORKLOAD:
            result.append(EvaluationWarning(
                code="HIGH_DAILY_LOAD",
                severity="WARNING",
                message=(
                    f"第 {stats.day_index + 1} 天加权负载 {stats.workload:.1f} "
                    f"(阈值 {HIGH_DAILY_WORKLOAD:.1f})"
                ),
                day_index=stats.day_index,
                entity_type="DAY",
                metric_key="workload",
                actual_value=stats.workload,
                threshold=float(HIGH_DAILY_WORKLOAD),
            ))
        if stats.last_activity_end is not None:
            local_end = stats.last_activity_end.astimezone(
                stats.last_activity_end.tzinfo
            )
            if local_end.hour >= LATE_DAY_END_HOUR:
                result.append(EvaluationWarning(
                    code="LATE_DAY_END",
                    severity="INFO",
                    message=(
                        f"第 {stats.day_index + 1} 天结束时间较晚 "
                        f"({local_end.strftime('%H:%M')})"
                    ),
                    day_index=stats.day_index,
                    entity_type="DAY",
                    metric_key="last_activity_end_hour",
                    actual_value=float(local_end.hour),
                    threshold=float(LATE_DAY_END_HOUR),
                ))
    for day in days:
        for leg in day.transit_legs:
            slack = transfer_slack_minutes(day, leg)
            if slack < TIGHT_TRANSFER_SLACK_MINUTES:
                result.append(EvaluationWarning(
                    code="TIGHT_TRANSFER",
                    severity="WARNING",
                    message=f"活动间换乘余量仅 {round(slack)} 分钟",
                    day_index=list(days).index(day),
                    entity_type="TRANSIT",
                    entity_id=leg.transit_id,
                    metric_key="slack_minutes",
                    actual_value=round(slack, 1),
                    threshold=float(TIGHT_TRANSFER_SLACK_MINUTES),
                ))
            if slack < LOW_BUFFER_SLACK_MINUTES:
                result.append(EvaluationWarning(
                    code="LOW_TIME_BUFFER",
                    severity="CRITICAL",
                    message=f"活动间换乘缓冲严重不足 ({round(slack)} 分钟)",
                    day_index=list(days).index(day),
                    entity_type="TRANSIT",
                    entity_id=leg.transit_id,
                    metric_key="slack_minutes",
                    actual_value=round(slack, 1),
                    threshold=float(LOW_BUFFER_SLACK_MINUTES),
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
                        message=(
                            f"步行路段较长 ({leg.duration_seconds // 60} 分钟, "
                            f"{leg.distance_meters}m)"
                        ),
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
    command: PlanningCreateCommand | PlanningReplanCommand | PlanningCandidateValidationCommand,
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
    # Fixed schedules: both the place and time window must match.
    fixed_count = len(constraints.fixed_schedules)
    if fixed_count > 0:
        covered = 0
        for schedule in constraints.fixed_schedules:
            if any(
                activity_covers_fixed_schedule(activity, schedule)
                for day in itinerary.days
                for activity in day.activities
            ):
                covered += 1
        if covered < fixed_count:
            score -= 5 * (fixed_count - covered)
    return max(0, score)


# ── Interest match ─────────────────────────────────────────────────────────

# Preference keyword → AMap typecode prefix (first two digits = big category).
# Activities whose type_code starts with any of these prefixes are considered
# a match for that preference.
_PREFERENCE_TYPECODE_MAP: dict[str, tuple[str, ...]] = {
    "美食": ("05",),          # 餐饮服务
    "餐饮": ("05",),
    "小吃": ("05",),
    "购物": ("06",),          # 购物服务
    "自然": ("11",),          # 风景名胜
    "风景": ("11",),
    "风光": ("11",),
    "山水": ("11",),
    "历史文化": ("08", "14"), # 体育休闲(含历史景点) + 科教文化(博物馆等)
    "历史": ("08", "14"),
    "文化": ("14", "08"),
    "古迹": ("08", "14"),
    "博物馆": ("14",),        # 科教文化服务
    "展览": ("14",),
    "艺术": ("14",),
    "娱乐": ("08",),          # 体育休闲服务
    "休闲": ("08", "11"),
    "户外": ("11", "08"),
    "运动": ("08",),
    "徒步": ("11",),
    "住宿": ("10",),          # 住宿服务
    "酒店": ("10",),
}

# Preference keywords that can also be matched by type_name substring.
_PREFERENCE_TYPENAME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "美食": ("餐饮", "餐厅", "美食", "小吃", "火锅", "面馆"),
    "购物": ("购物", "商场", "市场", "商业街", "专卖店"),
    "历史文化": ("博物馆", "纪念馆", "故居", "古迹", "寺庙", "教堂", "遗址", "古镇"),
    "自然": ("公园", "风景区", "山", "湖", "海", "岛", "森林", "湿地", "峡谷"),
    "娱乐": ("影院", "剧院", "游乐场", "KTV", "酒吧", "茶馆"),
    "运动": ("体育", "健身", "游泳", "滑雪", "高尔夫", "球场"),
    "住宿": ("酒店", "宾馆", "民宿", "客栈", "度假村"),
}


def score_interest_match(
    command: PlanningCreateCommand | PlanningReplanCommand | PlanningCandidateValidationCommand,
    itinerary: Itinerary,
) -> int:
    """Score how well the itinerary matches user preferences.

    Uses POI type_code (AMap classification) and type_name to check
    whether planned activities align with each stated preference.
    Returns 0–100.
    """
    constraints = command.payload.trip.constraints
    preferences = constraints.preferences
    if not preferences:
        return 100  # no explicit preferences → no penalty

    activities = tuple(
        activity for day in itinerary.days for activity in day.activities
    )
    if not activities:
        return 80  # fallback when no activities (should not happen in practice)

    # Build per-activity match signatures
    activity_signatures: list[set[str]] = []
    for a in activities:
        sig: set[str] = set()
        if a.type_code:
            sig.add(a.type_code[:2])  # big category prefix
        if a.type_name:
            sig.add(a.type_name)
        activity_signatures.append(sig)

    # For each preference, check if any activity matches
    matched_prefs = 0
    for pref in preferences:
        pref_key = pref.strip()
        if not pref_key:
            matched_prefs += 1  # empty preference → auto-match
            continue

        pref_lower = pref_key.lower()
        is_match = False

        # Check typecode prefix mapping
        code_prefixes = _PREFERENCE_TYPECODE_MAP.get(pref_key)
        if code_prefixes:
            for sig in activity_signatures:
                if any(cp in sig for cp in code_prefixes):
                    is_match = True
                    break

        # Check type_name substring mapping
        if not is_match:
            name_keywords = _PREFERENCE_TYPENAME_KEYWORDS.get(pref_key, ())
            if not name_keywords:
                # No mapping defined — check if preference word appears in any
                # activity type_name as a substring
                for sig in activity_signatures:
                    for token in sig:
                        if pref_lower in token.lower():
                            is_match = True
                            break
                    if is_match:
                        break
            else:
                for sig in activity_signatures:
                    for token in sig:
                        token_lower = token.lower()
                        if any(kw.lower() in token_lower for kw in name_keywords):
                            is_match = True
                            break
                    if is_match:
                        break

        if is_match:
            matched_prefs += 1

    # Score: coverage of preferences
    pref_coverage = matched_prefs / len(preferences)

    # Also factor activity-level coverage: what fraction of activities matched
    # at least one preference? This rewards itineraries where MOST activities
    # are relevant to stated interests.
    matched_activities = 0
    for sig in activity_signatures:
        act_matched = False
        for pref in preferences:
            pref_key = pref.strip()
            if not pref_key:
                act_matched = True
                break
            code_prefixes = _PREFERENCE_TYPECODE_MAP.get(pref_key)
            if code_prefixes and any(cp in sig for cp in code_prefixes):
                act_matched = True
                break
            name_keywords = _PREFERENCE_TYPENAME_KEYWORDS.get(pref_key)
            if name_keywords:
                for token in sig:
                    if any(kw.lower() in token.lower() for kw in name_keywords):
                        act_matched = True
                        break
                if act_matched:
                    break
        if act_matched:
            matched_activities += 1

    activity_ratio = matched_activities / len(activities) if activities else 0

    # Combined score: 70% preference coverage + 30% activity coverage
    score = round(pref_coverage * 70 + activity_ratio * 30)
    return max(0, min(100, score))


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
    command: PlanningCreateCommand | PlanningReplanCommand | PlanningCandidateValidationCommand,
    itinerary: Itinerary,
    budget_ctx: BudgetContext,
) -> list[str]:
    """Detect hard-constraint violations that should block completion.

    Thin adapter over the canonical feasibility rules: each rule is evaluated
    once through :func:`~trip_agent.feasibility.rules.core` and findings are
    flattened into the legacy message texts, in the legacy order (budget,
    date range, fixed schedules, duplicate POI, activity overlap).  An empty
    list means the result is safe to complete.
    """
    ctx = ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=budget_ctx,
    )
    assessments = (
        assess_budget_limit(ctx),
        assess_trip_date_range(ctx),
        assess_fixed_schedule_coverage(ctx),
        assess_duplicate_poi(ctx),
        assess_activity_overlap(ctx),
    )
    return [
        finding.message
        for assessment in assessments
        for finding in assessment.findings
    ]
