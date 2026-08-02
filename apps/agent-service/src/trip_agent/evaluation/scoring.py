"""Cross-language PlanEvaluation score calculation."""

from typing import Protocol


class DimensionScores(Protocol):
    """The five integer dimensions used by the stable evaluation contract."""

    constraint_satisfaction: int
    time_feasibility: int
    budget_fit: int
    route_efficiency: int
    interest_match: int


def weighted_overall_score(dimensions: DimensionScores) -> int:
    """Return the weighted score using integer half-up rounding.

    The integer numerator avoids binary floating-point drift and matches the
    Java consumer's positive-number ``Math.round`` semantics.
    """
    numerator = (
        dimensions.constraint_satisfaction * 30
        + dimensions.time_feasibility * 25
        + dimensions.budget_fit * 15
        + dimensions.route_efficiency * 15
        + dimensions.interest_match * 15
    )
    return (numerator + 50) // 100
