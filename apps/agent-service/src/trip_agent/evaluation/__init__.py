"""Deterministic plan evaluation and structured explanation generation.

Imports are lazy to avoid circular dependencies with the contracts
and domain modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from trip_agent.evaluation.models import (
    DecisionExplanation,
    EvaluationDimensions,
    EvaluationEvidence,
    EvaluationWarning,
    PlanEvaluation,
)

if TYPE_CHECKING:
    from trip_agent.evaluation.evaluator import PlanEvaluator
    from trip_agent.evaluation.explanations import (
        DeterministicPlanExplanationGenerator,
    )


def get_plan_evaluator() -> PlanEvaluator:
    """Factory — defers import of the evaluator to break circular chains."""
    from trip_agent.evaluation.evaluator import PlanEvaluator
    return PlanEvaluator()


def get_deterministic_explanation_generator() -> (
    DeterministicPlanExplanationGenerator
):
    from trip_agent.evaluation.explanations import (
        DeterministicPlanExplanationGenerator,
    )
    return DeterministicPlanExplanationGenerator()


__all__ = [
    "DecisionExplanation",
    "DeterministicPlanExplanationGenerator",
    "EvaluationDimensions",
    "EvaluationEvidence",
    "EvaluationWarning",
    "PlanEvaluation",
    "PlanEvaluator",
    "get_deterministic_explanation_generator",
    "get_plan_evaluator",
]
