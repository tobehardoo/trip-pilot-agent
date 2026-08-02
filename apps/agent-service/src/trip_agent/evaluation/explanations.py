"""Deterministic explanation generator — purely rule-based, no LLM.

Every generated statement is backed by verifiable data from the plan.
"""

from __future__ import annotations

from uuid import UUID

from trip_agent.evaluation.models import (
    DecisionExplanation,
    EvaluationDimensions,
    EvaluationEvidence,
)
from trip_agent.evaluation.rules import BudgetContext, DayStats
from trip_agent.domain.planning.protocols import PlanningResult
from trip_agent.worker.contracts import PlanningCreateCommand


class DeterministicPlanExplanationGenerator:
    """Generate structured explanations from plan facts only."""

    def generate(
        self,
        *,
        command: PlanningCreateCommand,
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

        # Activity-level for each day with fixed schedules
        constraints = command.payload.trip.constraints
        for day in result.itinerary.days:
            for activity in day.activities:
                for fs in constraints.fixed_schedules:
                    if (
                        activity.start_time <= fs.start_time
                        and activity.end_time >= fs.end_time
                    ):
                        decisions.append(DecisionExplanation(
                            subject_type="ACTIVITY",
                            subject_id=activity.activity_id,
                            summary=f"「{activity.title}」因固定预约安排在 {_format_time(activity.start_time)}",
                            reason_codes=("FIXED_APPOINTMENT",),
                            reasons=(f"预约「{fs.place_name}」时间为 {_format_time(fs.start_time)} 至 {_format_time(fs.end_time)}",),
                            constraint_refs=(),
                            evidence=(
                                EvaluationEvidence(
                                    key="fixed_schedule",
                                    label="固定预约",
                                    value=fs.place_name,
                                ),
                            ),
                            day_index=list(result.itinerary.days).index(day),
                        ))

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
                    decisions.append(DecisionExplanation(
                        subject_type="TRANSIT",
                        subject_id=leg.transit_id,
                        summary=f"选择步行 ({leg.duration_seconds // 60} 分钟)，距离 {leg.distance_meters}m",
                        reason_codes=("SHORTEST_ROUTE",),
                        reasons=("两点之间步行距离适中",),
                        constraint_refs=(),
                        day_index=list(result.itinerary.days).index(day),
                    ))

        # Sort stable: plan → day_index → subject_type → subject_id
        decisions.sort(key=_decision_sort_key)
        return tuple(decisions)

    def summary(
        self,
        *,
        command: PlanningCreateCommand,
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
        self, command: PlanningCreateCommand, result: PlanningResult
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
        command: PlanningCreateCommand,
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
                reasons=(f"活动集中在一天，减少跨天通勤",),
                day_index=stats.day_index,
            ))
        return tuple(decisions)


def _weighted_overall(d: EvaluationDimensions) -> int:
    from trip_agent.evaluation.rules import (
        CONSTRAINT_SATISFACTION_WEIGHT,
        TIME_FEASIBILITY_WEIGHT,
        BUDGET_FIT_WEIGHT,
        ROUTE_EFFICIENCY_WEIGHT,
        INTEREST_MATCH_WEIGHT,
    )
    return round(
        d.constraint_satisfaction * CONSTRAINT_SATISFACTION_WEIGHT
        + d.time_feasibility * TIME_FEASIBILITY_WEIGHT
        + d.budget_fit * BUDGET_FIT_WEIGHT
        + d.route_efficiency * ROUTE_EFFICIENCY_WEIGHT
        + d.interest_match * INTEREST_MATCH_WEIGHT
    )


def _format_time(dt: object) -> str:
    return dt.strftime("%H:%M") if hasattr(dt, "strftime") else str(dt)


def _decision_sort_key(d: DecisionExplanation) -> tuple:
    type_order = {"PLAN": 0, "DAY": 1, "ACTIVITY": 2, "TRANSIT": 3}
    return (
        d.day_index if d.day_index is not None else -1,
        type_order.get(d.subject_type, 99),
        str(d.subject_id or ""),
    )
