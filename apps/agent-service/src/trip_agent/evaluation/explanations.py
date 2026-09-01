"""Deterministic explanation generator — purely rule-based, no LLM.

Every generated statement is backed by verifiable data from the plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from trip_agent.domain.planning.protocols import PlanningResult
from trip_agent.evaluation.models import (
    DecisionExplanation,
    EvaluationDimensions,
    EvaluationEvidence,
)
from trip_agent.evaluation.rules import (
    BudgetContext,
    DayStats,
    activity_covers_fixed_schedule,
)
from trip_agent.worker.contracts import (
    PlanningCandidateValidationCommand,
    PlanningCreateCommand,
    PlanningReplanCommand,
)

PlanningCommand = (
    PlanningCreateCommand | PlanningReplanCommand | PlanningCandidateValidationCommand
)


class DeterministicPlanExplanationGenerator:
    """Generate structured explanations from plan facts only."""

    def generate(
        self,
        *,
        command: PlanningCommand,
        result: PlanningResult,
        budget_ctx: BudgetContext,
        day_stats: tuple[DayStats, ...],
    ) -> tuple[DecisionExplanation, ...]:
        decisions: list[DecisionExplanation] = []

        # Plan-level
        decisions.append(self._plan_level(command, result))

        # Day-level
        for ds in day_stats:
            decisions.extend(self._day_level(command, result, ds))

        # V2 P0-C: real planner decisions captured as in-process traces
        # (weather-aware mode choices, tight-budget demotion).  This wires the
        # reason-code vocabulary that existed but was never emitted (audit
        # §16.2: BUDGET_CONSTRAINT / TRANSIT_MODE had zero emitters).
        for trace in result.decision_traces:
            decisions.append(
                DecisionExplanation(
                    subject_type=trace.subject_type,  # type: ignore[arg-type]
                    subject_id=None,
                    summary=trace.summary,
                    reason_codes=tuple(trace.reason_codes),
                    reasons=tuple(trace.reasons),
                    constraint_refs=(),
                    evidence=tuple(
                        EvaluationEvidence(key=item.key, label=item.label, value=item.value)
                        for item in trace.evidence
                    ),
                )
            )

        # Activity-level for each day with fixed schedules
        constraints = command.payload.trip.constraints
        for day in result.itinerary.days:
            for activity in day.activities:
                for fs in constraints.fixed_schedules:
                    if activity_covers_fixed_schedule(activity, fs):
                        decisions.append(
                            DecisionExplanation(
                                subject_type="ACTIVITY",
                                subject_id=activity.activity_id,
                                summary=(
                                    f"「{activity.title}」因固定预约安排在 "
                                    f"{_format_time(activity.start_time)}"
                                ),
                                reason_codes=("FIXED_APPOINTMENT",),
                                reasons=(
                                    f"预约「{fs.place_name}」时间为 "
                                    f"{_format_time(fs.start_time)} 至 "
                                    f"{_format_time(fs.end_time)}",
                                ),
                                constraint_refs=(),
                                evidence=(
                                    EvaluationEvidence(
                                        key="fixed_schedule",
                                        label="固定预约",
                                        value=fs.place_name,
                                    ),
                                ),
                                day_index=list(result.itinerary.days).index(day),
                            )
                        )

        # Transit-level with fallback
        for day in result.itinerary.days:
            for leg in day.transit_legs:
                if leg.fallback_operation is not None:
                    decisions.append(DecisionExplanation(
                        subject_type="TRANSIT",
                        subject_id=leg.transit_id,
                        summary="此路段使用 Demo 数据，因为真实路线服务不可用",
                        reason_codes=("PROVIDER_CONSTRAINT",),
                        reasons=(f"Provider 错误: {leg.fallback_operation.error_category}",),
                        constraint_refs=(),
                        evidence=(
                            EvaluationEvidence(
                                key="provider_fallback",
                                label="降级 Provider",
                                value=f"DEMO (retry={leg.fallback_operation.retry_count})",
                            ),
                        ),
                        day_index=list(result.itinerary.days).index(day),
                    ))

                if leg.mode == "WALKING" and leg.duration_seconds >= 30 * 60:
                    decisions.append(
                        DecisionExplanation(
                            subject_type="TRANSIT",
                            subject_id=leg.transit_id,
                            summary=(
                                f"选择步行 ({leg.duration_seconds // 60} 分钟)，"
                                f"距离 {leg.distance_meters}m"
                            ),
                            reason_codes=("SHORTEST_ROUTE",),
                            reasons=("两点之间步行距离适中",),
                            constraint_refs=(),
                            day_index=list(result.itinerary.days).index(day),
                        )
                    )

        # Sort stable: plan → day_index → subject_type → subject_id
        decisions.sort(key=_decision_sort_key)
        return tuple(decisions)

    def summary(
        self,
        *,
        command: PlanningCommand,
        result: PlanningResult,
        dimensions: EvaluationDimensions,
    ) -> str:
        constraints = command.payload.trip.constraints
        fixed_count = len(constraints.fixed_schedules)
        must_count = len(constraints.must_visit_places)
        fallback_count = len(result.fallback_operations)

        parts: list[str] = [
            f"行程整体质量 {_weighted_overall(dimensions)}/100",
        ]
        if fixed_count > 0:
            parts.append(f"满足 {fixed_count} 个固定预约")
        if must_count > 0:
            parts.append(f"覆盖 {must_count} 个必去地点")
        if fallback_count > 0:
            parts.append(f"{fallback_count} 个路段使用 Demo 降级")
        return "，".join(parts) + "。"

    def _plan_level(
        self,
        command: PlanningCommand,
        result: PlanningResult,
    ) -> DecisionExplanation:
        constraints = command.payload.trip.constraints
        fixed_count = len(constraints.fixed_schedules)
        must_count = len(constraints.must_visit_places)

        reasons: list[str] = []
        codes: list[str] = []
        if fixed_count > 0:
            codes.append("FIXED_APPOINTMENT")
            reasons.append(f"优先满足 {fixed_count} 个固定预约")
        if must_count > 0:
            codes.append("MUST_VISIT")
            reasons.append(f"覆盖 {must_count} 个必去地点")
        if result.fallback_operations:
            codes.append("PROVIDER_CONSTRAINT")
            reasons.append(f"{len(result.fallback_operations)} 个路段使用 Demo 降级")

        if not codes:
            codes.append("TIME_OPTIMIZATION")
            reasons.append("基于时间优化安排活动顺序")

        return DecisionExplanation(
            subject_type="PLAN",
            summary=f"「{result.itinerary.title}」基于约束求解生成",
            reason_codes=tuple(codes),
            reasons=tuple(reasons),
            evidence=(
                EvaluationEvidence(
                    key="provider", label="数据 Provider", value=result.provider
                ),
            ),
        )

    def _day_level(
        self,
        command: PlanningCommand,
        result: PlanningResult,
        stats: DayStats,
    ) -> tuple[DecisionExplanation, ...]:
        decisions: list[DecisionExplanation] = []
        if stats.activity_count >= 2:
            decisions.append(DecisionExplanation(
                subject_type="DAY",
                subject_id=None,
                summary=f"第 {stats.day_index + 1} 天安排了 {stats.activity_count} 个活动",
                reason_codes=("REGIONAL_GROUPING",),
                reasons=("活动集中在一天，减少跨天通勤",),
                day_index=stats.day_index,
            ))
        return tuple(decisions)


def _weighted_overall(d: EvaluationDimensions) -> int:
    from trip_agent.evaluation.scoring import weighted_overall_score

    return weighted_overall_score(d)


def _format_time(dt: object) -> str:
    return dt.strftime("%H:%M") if hasattr(dt, "strftime") else str(dt)


def _decision_sort_key(d: DecisionExplanation) -> tuple:
    type_order = {"PLAN": 0, "DAY": 1, "ACTIVITY": 2, "TRANSIT": 3}
    return (
        d.day_index if d.day_index is not None else -1,
        type_order.get(d.subject_type, 99),
        str(d.subject_id or ""),
    )


# ── V3 P2-3: user-facing themed explanations (read-side only) ────────────────

type ExplanationTopic = Literal[
    "WEATHER",
    "BUDGET",
    "PACE",
    "INTEREST",
    "FIXED_SCHEDULE",
    "POI_GOVERNANCE",
]

_TOPIC_TITLES: dict[str, str] = {
    "WEATHER": "天气调整",
    "BUDGET": "预算控制",
    "PACE": "旅行节奏",
    "INTEREST": "兴趣匹配",
    "FIXED_SCHEDULE": "固定安排",
    "POI_GOVERNANCE": "景点甄选",
}

_CODE_TO_TOPIC: dict[str, str] = {
    "TRANSIT_MODE": "WEATHER",
    "BUDGET_CONSTRAINT": "BUDGET",
    "PACE_POLICY": "PACE",
    "INTEREST_MATCH": "INTEREST",
    "FIXED_APPOINTMENT": "FIXED_SCHEDULE",
    "PROVIDER_CONSTRAINT": "POI_GOVERNANCE",
}


@dataclass(frozen=True, slots=True)
class ThemedExplanation:
    """One user-readable theme ("为什么这份方案适合你") with its lines."""

    topic: ExplanationTopic
    title: str
    lines: tuple[str, ...]


def themed_user_explanations(
    decisions: tuple[DecisionExplanation, ...],
) -> tuple[ThemedExplanation, ...]:
    """Group existing decision explanations into user-facing themes.

    Pure read-side assembly (V3 P2-3): no planning decision is made or
    changed here — every line already exists as a DecisionExplanation
    summary produced by the policies.  Topics with no decisions are absent;
    the remaining ones keep a deterministic order.
    """
    lines_by_topic: dict[str, list[str]] = {}
    for decision in decisions:
        codes = decision.reason_codes
        if "FIXED_APPOINTMENT" in codes:
            # a fixed-slot decision (e.g. the deadline DRIVING) is about the
            # appointment, not about weather — TRANSIT_MODE beside it does
            # not make it a weather theme
            topics: tuple[str, ...] = ("FIXED_SCHEDULE",)
        else:
            topics = tuple(
                _CODE_TO_TOPIC.get(code) for code in codes
            )
        for topic in topics:
            if topic is None:
                continue
            bucket = lines_by_topic.setdefault(topic, [])
            if decision.summary not in bucket:
                bucket.append(decision.summary)
    topic_order = (
        "WEATHER",
        "BUDGET",
        "PACE",
        "INTEREST",
        "FIXED_SCHEDULE",
        "POI_GOVERNANCE",
    )
    ordered = [topic for topic in topic_order if topic in lines_by_topic]
    return tuple(
        ThemedExplanation(
            topic=topic,  # type: ignore[arg-type]
            title=_TOPIC_TITLES[topic],
            lines=tuple(lines_by_topic[topic]),
        )
        for topic in ordered
    )
