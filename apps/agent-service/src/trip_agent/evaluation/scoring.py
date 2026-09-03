"""Cross-language PlanEvaluation score calculation."""

from typing import Protocol


class DimensionScores(Protocol):
    """Dimension scores used by the versioned evaluation contract."""

    constraint_satisfaction: int
    time_feasibility: int
    budget_fit: int | None
    route_efficiency: int
    interest_match: int | None
    evidence_strength: int | None


def weighted_overall_score(dimensions: DimensionScores) -> int:
    """Return the weighted score using integer half-up rounding.

    M0 (rule-v6): the evidence dimension draws weight from constraint
    satisfaction and time feasibility (25/22/15/15/15/8 = 100).  The integer
    numerator avoids binary floating-point drift and matches the Java
    consumer's positive-number ``Math.round`` semantics.  Optional dimensions
    (budget, interest, evidence) are excluded when ``None`` — the same
    renormalisation semantics as before.
    """
    weighted_scores = (
        (dimensions.constraint_satisfaction, 25),
        (dimensions.time_feasibility, 22),
        (dimensions.budget_fit, 15),
        (dimensions.route_efficiency, 15),
        (dimensions.interest_match, 15),
        (dimensions.evidence_strength, 8),
    )
    applicable = tuple(
        (score, weight)
        for score, weight in weighted_scores
        if score is not None
    )
    total_weight = sum(weight for _, weight in applicable)
    numerator = sum(score * weight for score, weight in applicable)
    return (numerator + total_weight // 2) // total_weight
