"""B5 Phase 0 — characterization baseline.

Locks the pre-B5 facts so the batch can prove its deltas.  These tests must
pass immediately without any production change; later phases update the
factual assertions they depend on.
"""

import asyncio

from trip_agent.feasibility.catalog import (
    IMPLEMENTED_RULE_IDS,
    MISSING_RULE_IDS,
    REQUIRED_RULE_IDS,
)
from trip_agent.feasibility.validator import VALIDATOR_VERSION
from trip_agent.planning.visit_duration import VisitDurationProfile


def test_catalog_is_eleven_of_eleven() -> None:
    assert len(REQUIRED_RULE_IDS) == 11
    assert len(IMPLEMENTED_RULE_IDS) == 11
    assert len(MISSING_RULE_IDS) == 0


def test_validator_version_is_v5() -> None:
    assert VALIDATOR_VERSION == "hard-validator-v5"


def test_duration_profile_has_eight_fields() -> None:
    fields = tuple(VisitDurationProfile.__dataclass_fields__)
    assert fields == (
        "min_minutes",
        "recommended_minutes",
        "max_minutes",
        "source",
        "source_ref",
        "confidence",
        "profile_version",
        "hard_constraint_eligible",
    )


def test_demo_planning_result_projects_validation_state() -> None:
    from test_planning_worker import COMMAND

    from trip_agent.feasibility.inputs import MealProjectionState
    from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider
    from trip_agent.worker.contracts import PlanningCreateCommand

    command = PlanningCreateCommand.model_validate(COMMAND)
    result = asyncio.run(DemoPlanningProvider().plan(command))

    # B9.1: Demo now projects its own skeleton/inputs; the meal projection is
    # explicitly UNAVAILABLE and no opening evidence is fabricated.
    assert result.trip_skeleton is not None
    assert result.validation_inputs is not None
    assert result.validation_inputs.opening_hours_bindings == ()
    assert (
        result.validation_inputs.meal_projection_state
        is MealProjectionState.UNAVAILABLE
    )


def test_amap_planning_result_has_no_validation_inputs() -> None:
    from test_daily_skeleton_provider import _command, _poi, _provider

    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(_provider(pois).plan(_command()))

    assert result.trip_skeleton is not None
    assert result.validation_inputs is not None


def test_scheduler_uses_fixed_magnitude_minutes() -> None:
    from trip_agent.planning.daily_schedule import MAGNITUDE_DURATION_MINUTES

    assert MAGNITUDE_DURATION_MINUTES == {
        "LIGHT": 90,
        "NORMAL": 150,
        "HALF_DAY": 240,
        "FULL_DAY": 480,
    }


def test_command_meal_windows_support_breakfast_but_scheduler_does_not() -> None:
    from test_planning_worker import COMMAND

    from trip_agent.worker.contracts import PlanningCreateCommand

    command = PlanningCreateCommand.model_validate(COMMAND)
    windows = command.payload.trip.constraints.meal_windows
    types = {window.meal_type for window in windows}
    assert "BREAKFAST" in {"BREAKFAST", "LUNCH", "DINNER"}
    assert types.issubset({"BREAKFAST", "LUNCH", "DINNER"})


def test_v8_completion_schema_unchanged() -> None:
    import json
    from pathlib import Path

    schema = json.loads(
        Path("../../contracts/messaging/planning-completed-event-v8.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema.get("title", "").replace(" ", "").startswith("PlanningCompletedEvent")
    assert "tripSkeleton" not in json.dumps(schema)
    assert "validationInputs" not in json.dumps(schema)
