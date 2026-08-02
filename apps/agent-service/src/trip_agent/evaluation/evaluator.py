"""PlanEvaluator — deterministic, read-only, side-effect-free."""

from datetime import datetime, timezone

from trip_agent.evaluation.models import (
    EvaluationDimensions,
    EvaluationWarning,
    PlanEvaluation,
)
from trip_agent.evaluation.rules import (
    budget_warning,
    build_budget_context,
    compute_day_stats,
    detect_hard_constraint_violations,
    provider_fallback_warnings,
    route_warnings,
    score_budget_fit,
    score_constraint_satisfaction,
    score_interest_match,
    score_route_efficiency,
    score_time_feasibility,
    time_warnings,
    CONSTRAINT_SATISFACTION_WEIGHT,
    TIME_FEASIBILITY_WEIGHT,
    BUDGET_FIT_WEIGHT,
    ROUTE_EFFICIENCY_WEIGHT,
    INTEREST_MATCH_WEIGHT,
)
from trip_agent.evaluation.explanations import (
    DeterministicPlanExplanationGenerator,
)

EVALUATOR_VERSION = "rule-v1"


class PlanEvaluator:
    """Stateless, deterministic plan evaluator.

    Reads PlanningResult + original command, produces PlanEvaluation.
    Never modifies the plan.  Never calls external services.
    """

    def __init__(
        self,
        *,
        clock: object | None = None,
        explanations: DeterministicPlanExplanationGenerator | None = None,
    ) -> None:
        self._clock = clock or datetime
        self._explanations = explanations or DeterministicPlanExplanationGenerator()

    # ── public API ──────────────────────────────────────────────────────

    def evaluate(
        self,
        command: object,
        result: object,
    ) -> PlanEvaluation:
        """Produce a complete, deterministic plan evaluation.

        Raises PlanningProviderError with DATA_QUALITY_ERROR when hard
        constraints are violated — such results must not complete.
        """
        itinerary = result.itinerary
        budget_ctx = build_budget_context(command, itinerary)
        day_stats = compute_day_stats(itinerary.days)

        # Guard: hard constraint violations block completion
        violations = detect_hard_constraint_violations(
            command, itinerary, budget_ctx
        )
        if violations:
            # Lazy import to avoid circular dependency
            from trip_agent.providers.errors import PlanningProviderError
            raise PlanningProviderError(
                "\n".join(violations),
                category="DATA_QUALITY_ERROR",
                provider="PLANNER",
            )

        constraint_sat = score_constraint_satisfaction(command, itinerary)
        time_feas = score_time_feasibility(itinerary.days, day_stats)
        budget_fit = score_budget_fit(budget_ctx)
        route_eff = score_route_efficiency(day_stats)
        interest = score_interest_match(command)

        dimensions = EvaluationDimensions(
            constraint_satisfaction=constraint_sat,
            time_feasibility=time_feas,
            budget_fit=budget_fit,
            route_efficiency=route_eff,
            interest_match=interest,
        )

        # Collect warnings
        warnings: list[EvaluationWarning] = []
        warnings.extend(budget_warning(budget_ctx))
        warnings.extend(time_warnings(itinerary.days, day_stats))
        warnings.extend(route_warnings(itinerary.days))
        warnings.extend(provider_fallback_warnings(result.fallback_operations))

        # Generate decisions
        decisions = self._explanations.generate(
            command=command,
            result=result,
            budget_ctx=budget_ctx,
            day_stats=day_stats,
        )

        evaluated_at = (
            self._clock.now(timezone.utc)
            if hasattr(self._clock, "now")
            else datetime.now(timezone.utc)
        )

        return PlanEvaluation(
            schema_version=1,
            evaluator_version=EVALUATOR_VERSION,
            feasible=True,
            overall_score=_weighted_score(dimensions),
            dimensions=dimensions,
            warnings=tuple(warnings),
            decisions=decisions,
            summary=self._explanations.summary(
                command=command, result=result, dimensions=dimensions
            ),
            evaluated_at=evaluated_at,
        )


def _weighted_score(d: EvaluationDimensions) -> int:
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
