from __future__ import annotations

import json
from pathlib import Path

import pytest

from trip_agent.evaluation.models import PlanEvaluation

FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[3]
    / "contracts"
    / "fixtures"
    / "planning-completed-event-v6"
)


@pytest.mark.parametrize(
    "fixture_name",
    (
        "completion-v6-evaluation-clean.json",
        "completion-v6-evaluation-warnings.json",
        "completion-v6-evaluation-mixed-provider.json",
        "completion-v6-evaluation-fixed-appointment.json",
    ),
)
def test_python_model_reads_shared_evaluation_fixtures(fixture_name: str) -> None:
    event = json.loads((FIXTURE_DIRECTORY / fixture_name).read_text(encoding="utf-8"))

    evaluation = PlanEvaluation.model_validate(event["payload"]["evaluation"])

    assert evaluation.schema_version == 1
    assert evaluation.evaluator_version == "rule-v1"
    assert evaluation.feasible is True


def test_legacy_shared_fixture_remains_valid_without_evaluation() -> None:
    event = json.loads(
        (FIXTURE_DIRECTORY / "completion-v6-legacy-without-evaluation.json").read_text(
            encoding="utf-8"
        )
    )

    assert "evaluation" not in event["payload"]
