import asyncio
import json
import logging
from pathlib import Path

from trip_agent.domain.planning.protocols import PlanningProviderError
from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider
from trip_agent.worker.contracts import PlanningCreateCommand
from trip_agent.workflow.planner_pipeline import FallbackPlanningProvider


def test_demo_fallback_logs_reason_and_planning_correlation_ids(
    caplog: object,
) -> None:
    fixture = Path(__file__).parent / "fixtures" / "real_provider" / "guangzhou_day_a.json"
    command = PlanningCreateCommand.model_validate(
        json.loads(fixture.read_text(encoding="utf-8"))["command"]
    )

    class FailedProvider:
        async def plan(self, _command: PlanningCreateCommand):
            raise PlanningProviderError("PROVIDER_RATE_LIMITED")

        async def replan(self, _command: object):
            raise AssertionError("replan is not part of this test")

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(
            FallbackPlanningProvider(FailedProvider(), DemoPlanningProvider()).plan(command)
        )

    assert result.provider == "DEMO"
    assert "planning_provider_fallback" in caplog.text
    assert "PROVIDER_RATE_LIMITED" in caplog.text
    assert str(command.trip_id) in caplog.text
    assert str(command.task_id) in caplog.text
    assert str(command.trace_id) in caplog.text
