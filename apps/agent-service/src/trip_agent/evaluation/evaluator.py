"""PlanEvaluator — deterministic, read-only, side-effect-free."""

from datetime import UTC, datetime

from trip_agent.domain.planning.protocols import PlanningResult
from trip_agent.evaluation.explanations import (
    DeterministicPlanExplanationGenerator,
)
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
)
from trip_agent.evaluation.scoring import weighted_overall_score
from trip_agent.worker.contracts import (
    PlanningCandidateValidationCommand,
    PlanningCreateCommand,
    PlanningReplanCommand,
)

EVALUATOR_VERSION = "rule-v3"


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
        command: PlanningCreateCommand | PlanningReplanCommand | PlanningCandidateValidationCommand,
        result: PlanningResult,
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
            from trip_agent.providers.errors import (
                PlanningProviderError,
                ProviderErrorCategory,
                ProviderFailureDetails,
                ProviderOperation,
            )
            operation = (
                ProviderOperation.REPLANNING
                if command.payload.task_type == "REPLAN"
                else ProviderOperation.PLANNING
            )
            raise PlanningProviderError(ProviderFailureDetails(
                category=ProviderErrorCategory.DATA_QUALITY_ERROR,
                error_code="PLAN_EVALUATION_DATA_QUALITY_ERROR",
                provider="PLANNER",
                operation=operation,
                retryable=False,
                fallback_allowed=False,
                safe_provider_code=None,
                safe_message="\n".join(violations),
                retry_count=0,
                cause_type=None,
            ))

        constraint_sat = score_constraint_satisfaction(command, itinerary)
        time_feas = score_time_feasibility(itinerary.days, day_stats)
        budget_fit = (
            score_budget_fit(budget_ctx)
            if budget_ctx.budget_amount is not None
            else None
        )
        route_eff = score_route_efficiency(day_stats)
        interest = (
            score_interest_match(command, itinerary)
            if command.payload.trip.constraints.preferences
            else None
        )

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
            self._clock.now(UTC)
            if hasattr(self._clock, "now")
            else datetime.now(UTC)
        )

        return PlanEvaluation(
            schema_version=2,
            evaluator_version=EVALUATOR_VERSION,
            feasible=True,
            overall_score=weighted_overall_score(dimensions),
            dimensions=dimensions,
            warnings=tuple(warnings),
            decisions=decisions,
            summary=self._explanations.summary(
                command=command, result=result, dimensions=dimensions
            ),
            evaluated_at=evaluated_at,
        )
