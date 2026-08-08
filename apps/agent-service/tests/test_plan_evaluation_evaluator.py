from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from plan_evaluation_support import make_command, make_result
from test_local_replanning import REPLAN_COMMAND

from trip_agent.evaluation.evaluator import PlanEvaluator
from trip_agent.providers.errors import PlanningProviderError
from trip_agent.worker.contracts import PlanningReplanCommand


class FrozenClock:
    @classmethod
    def now(cls, tz: object | None = None) -> datetime:
        return datetime(2026, 8, 2, 12, 30, tzinfo=UTC)


def test_evaluator_is_byte_deterministic_with_an_injected_clock() -> None:
    evaluator = PlanEvaluator(clock=FrozenClock)
    command = make_command(preferences=("food",))
    result = make_result()

    first = evaluator.evaluate(command, result)
    repeated = evaluator.evaluate(command, result)

    assert first.model_dump_json(by_alias=True) == repeated.model_dump_json(by_alias=True)
    assert first.evaluated_at == datetime(2026, 8, 2, 12, 30, tzinfo=UTC)
    # DEMO activities have no type info, so "food" pref is unmatched.
    assert first.dimensions.interest_match == 0


def test_evaluator_marks_missing_budget_and_preferences_not_applicable() -> None:
    evaluation = PlanEvaluator(clock=FrozenClock).evaluate(
        make_command(budget_amount=None, preferences=()),
        make_result(),
    )

    assert evaluation.schema_version == 2
    assert evaluation.evaluator_version == "rule-v2"
    assert evaluation.dimensions.budget_fit is None
    assert evaluation.dimensions.interest_match is None


def test_evaluator_blocks_over_budget_completion_with_data_quality_error() -> None:
    evaluator = PlanEvaluator(clock=FrozenClock)

    with pytest.raises(PlanningProviderError, match="exceeds budget") as captured:
        evaluator.evaluate(
            make_command(budget_amount=Decimal("1000.00")),
            make_result(estimated_total_cost=Decimal("1000.01")),
        )

    assert captured.value.details.category == "DATA_QUALITY_ERROR"
    assert captured.value.details.provider == "PLANNER"


def test_replan_data_quality_failure_uses_the_replanning_operation() -> None:
    raw = deepcopy(REPLAN_COMMAND)
    raw["payload"]["trip"]["constraints"]["fixedSchedules"] = [{
        "placeName": "Missing appointment",
        "startTime": "2026-08-01T09:15:00Z",
        "endTime": "2026-08-01T09:45:00Z",
    }]
    command = PlanningReplanCommand.model_validate(raw)

    with pytest.raises(PlanningProviderError) as captured:
        PlanEvaluator(clock=FrozenClock).evaluate(command, make_result())

    assert captured.value.details.operation == "REPLANNING"
