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


def get_plan_evaluator() -> PlanEvaluator:
    """Factory — defers import of the evaluator to break circular chains."""
    from trip_agent.evaluation.evaluator import PlanEvaluator
    return PlanEvaluator()


__all__ = [
    "DecisionExplanation",
    "EvaluationDimensions",
    "EvaluationEvidence",
    "EvaluationWarning",
    "PlanEvaluation",
    "PlanEvaluator",
    "get_plan_evaluator",
]
