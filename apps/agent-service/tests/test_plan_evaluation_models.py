from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from trip_agent.evaluation.models import EvaluationDimensions, PlanEvaluation


def _dimensions() -> EvaluationDimensions:
    return EvaluationDimensions(
        constraint_satisfaction=100,
        time_feasibility=96,
        budget_fit=90,
        route_efficiency=80,
        interest_match=80,
    )


def test_plan_evaluation_accepts_the_exact_weighted_score_and_camel_case_wire_shape() -> None:
    evaluation = PlanEvaluation(
        evaluator_version="rule-v1",
        feasible=True,
        overall_score=92,
        dimensions=_dimensions(),
        summary="Deterministic quality summary",
        evaluated_at=datetime(2026, 8, 2, tzinfo=UTC),
    )

    wire = evaluation.model_dump(mode="json", by_alias=True)

    assert wire["overallScore"] == 92
    assert wire["dimensions"]["constraintSatisfaction"] == 100
    assert wire["evaluatedAt"] == "2026-08-02T00:00:00Z"


def test_plan_evaluation_rounds_half_up_like_the_java_consumer() -> None:
    dimensions = EvaluationDimensions(
        constraint_satisfaction=100,
        time_feasibility=100,
        budget_fit=100,
        route_efficiency=90,
        interest_match=100,
    )

    evaluation = PlanEvaluation(
        evaluator_version="rule-v1",
        feasible=True,
        overall_score=99,
        dimensions=dimensions,
        summary="Cross-language half-up rounding",
        evaluated_at=datetime(2026, 8, 2, tzinfo=UTC),
    )

    assert evaluation.overall_score == 99


@pytest.mark.parametrize(
    ("override", "message"),
    (
        ({"overall_score": 91}, "must equal weighted sum"),
        ({"evaluated_at": datetime(2026, 8, 2)}, "must include a timezone"),
        ({"evaluator_version": "latest"}, "String should match pattern"),
    ),
)
def test_plan_evaluation_rejects_invalid_contract_states(
    override: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "evaluator_version": "rule-v1",
        "feasible": True,
        "overall_score": 92,
        "dimensions": _dimensions(),
        "summary": "Deterministic quality summary",
        "evaluated_at": datetime(2026, 8, 2, tzinfo=UTC),
    }
    values.update(override)

    with pytest.raises(ValidationError, match=message):
        PlanEvaluation(**values)
