"""P3.4: deterministic replay harness for the agent dialog path.

Runs scripted conversations through the production processor stack — real
demo builder, real structural gate, in-memory trajectory repository, no
keys — and asserts the invariants Gate 2 needs: bounded loops, structured
failures, no silent crashes, and emitted itineraries that pass the gate.

Execute directly: ``uv run python benchmarks/agent_trajectory/run_agent_trajectory.py``
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from trip_agent.agent import (
    AgentLoop,
    AgentRunStarted,
    AgentState,
    Decision,
    DemoItineraryBuilder,
    StructuralFeasibilityGate,
    ToolCall,
    ToolRegistry,
    ToolRuntime,
)
from trip_agent.platform_util import run_async
from trip_agent.worker.agent_processor import AgentDialogProcessor
from trip_agent.worker.contracts import AgentResumeCommand, AgentStartCommand


class InMemoryRunRepository:
    """Minimal trajectory repository for offline replay (no database)."""

    def __init__(self) -> None:
        self.checkpoints: dict[str, AgentState] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.existing: dict[str, str] = {}

    async def start_run(
        self, *, run_id: str, command_event_id: str | None, trip_id: str | None
    ) -> AgentRunStarted:
        if command_event_id and command_event_id in self.existing:
            return AgentRunStarted(run_id=self.existing[command_event_id], created=False)
        if command_event_id:
            self.existing[command_event_id] = run_id
        self.runs[run_id] = {"status": "RUNNING"}
        return AgentRunStarted(run_id=run_id, created=True)

    async def record_step(self, **_kwargs: Any) -> None:
        return None

    async def save_checkpoint(self, *, run_id: str, state: AgentState) -> None:
        self.checkpoints[run_id] = state

    async def load_checkpoint(self, run_id: str) -> AgentState | None:
        return self.checkpoints.get(run_id)

    async def checkpoint_updated_at(self, run_id: str) -> datetime | None:
        return datetime.now(UTC)

    async def finish_run(self, *, run_id: str, status: str, **_kwargs: Any) -> None:
        self.runs[run_id]["status"] = status

    async def load_run(self, run_id: str) -> Any:
        run = self.runs.get(run_id)
        return SimpleNamespace(status=run["status"]) if run else None

    async def count_steps(self, run_id: str) -> int:
        return 0


from types import SimpleNamespace  # noqa: E402  (used by load_run above)


class ReplayPolicyDecider:
    """Deterministic replay policy: confirm what the message names."""

    async def decide(self, state: AgentState) -> Decision:
        destination = state.slots.get("destination")
        start_date = state.slots.get("start_date")
        message = state.user_message or ""

        if "不想去" in message:
            rejected = message.split("不想去", 1)[1].split("，")[0].strip()
            # Fire the rejection only once: when the destination is undecided,
            # or when the currently confirmed value is exactly the rejected one.
            if not destination.hard or destination.value == rejected:
                values: dict[str, Any] = {}
                if "改去" in message:
                    values["destination"] = message.split("改去", 1)[1].strip()
                return Decision(
                    thought="the user rejected a destination",
                    call=ToolCall(
                        "update_constraints",
                        {
                            "values": values,
                            "rejections": {"destination": rejected},
                            "evidence": message,
                        },
                    ),
                    strategy="REPLAN",
                )

        if destination.hard and start_date.hard:
            builds = [obs for obs in state.observations if obs.tool == "build_itinerary"]
            if builds and not builds[-1].ok:
                return Decision(
                    thought="demo mode cannot verify must-visit places",
                    call=ToolCall(
                        "ask_user",
                        {"question": "必去地点在演示模式无法验证，请调整后再试。"},
                    ),
                    strategy="CLARIFY",
                )
            if state.candidate_itinerary is None:
                return Decision(
                    thought="build the draft",
                    call=ToolCall("build_itinerary"),
                    strategy="DIRECT",
                )
            if not any(
                obs.tool == "validate_itinerary" and obs.ok for obs in state.observations
            ):
                return Decision(
                    thought="gate the draft",
                    call=ToolCall("validate_itinerary"),
                    strategy="DIRECT",
                )
            return Decision(thought="done", answer="行程已生成。", strategy="DIRECT")

        if not destination.hard:
            for city in ("成都", "北京"):
                if city in message:
                    values = {"destination": city}
                    if "必去" in message:
                        values["must_visit"] = [message.split("必去", 1)[1].split("，")[0].strip()]
                    return Decision(
                        thought="confirm destination",
                        call=ToolCall(
                            "update_constraints", {"values": values, "evidence": message}
                        ),
                        strategy="CLARIFY",
                    )
            return Decision(
                thought="ask city",
                call=ToolCall(
                    "ask_user",
                    {
                        "question": "你想去哪个城市？",
                        "options": ["成都", "北京"],
                        "expected_type": "choice",
                    },
                ),
                strategy="CLARIFY",
            )

        end_day = "10月7日" if "10月7日" in message else "10月3日"
        if "10月1日" in message:
            return Decision(
                thought="confirm dates",
                call=ToolCall(
                    "update_constraints",
                    {
                        "values": {"start_date": "10月1日", "end_date": end_day},
                        "evidence": message,
                    },
                ),
                strategy="CLARIFY",
            )
        return Decision(
            thought="ask dates",
            call=ToolCall("ask_user", {"question": "行程从哪天开始？", "expected_type": "text"}),
            strategy="CLARIFY",
        )


@dataclass(frozen=True)
class Scenario:
    name: str
    messages: tuple[str, ...]
    expect_stop: str
    expect_destination: str | None = None
    expect_infeasible: bool = False


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="happy-path-emit",
        messages=("十一想去成都玩", "就去成都", "10月1日到10月3日出发"),
        expect_stop="EMITTED",
        expect_destination="成都",
    ),
    Scenario(
        name="clarification-loop",
        messages=("出去玩", "随便", "成都吧", "10月1日到10月3日"),
        expect_stop="EMITTED",
        expect_destination="成都",
    ),
    Scenario(
        name="rejected-value",
        messages=("想去成都玩", "不想去成都，改去北京", "10月1日到10月3日"),
        expect_stop="EMITTED",
        expect_destination="北京",
    ),
    Scenario(
        name="infeasible-must-visit",
        messages=("想去成都玩，必去武侯祠", "就去成都", "10月1日到10月3日，必去武侯祠"),
        expect_stop="WAITING_USER",
        expect_infeasible=True,
    ),
    Scenario(
        name="boundary-dates",
        messages=("十一去北京", "就去北京", "10月1日到10月7日"),
        expect_stop="EMITTED",
        expect_destination="北京",
    ),
)


def _build_processor() -> AgentDialogProcessor:
    async def publisher(_event: Any) -> None:
        return None

    def loop_factory() -> AgentLoop:
        registry = ToolRegistry.with_runtime(
            ToolRuntime(
                itinerary_builder=DemoItineraryBuilder(),
                feasibility=StructuralFeasibilityGate(),
            )
        )
        return AgentLoop(decider=ReplayPolicyDecider(), tools=registry)

    return AgentDialogProcessor(
        repository=InMemoryRunRepository(),
        publisher=publisher,
        loop_factory=loop_factory,
    )


def _start_command(message: str) -> AgentStartCommand:
    return AgentStartCommand(
        eventType="AGENT_START",
        schemaVersion=1,
        eventId=uuid4(),
        traceId=uuid4(),
        tripId=uuid4(),
        occurredAt=datetime.now(UTC),
        payload={"message": message},
    )


def _resume_command(run_id: str, message: str) -> AgentResumeCommand:
    return AgentResumeCommand(
        eventType="AGENT_RESUME",
        schemaVersion=1,
        eventId=uuid4(),
        traceId=uuid4(),
        tripId=uuid4(),
        runId=UUID(run_id),
        occurredAt=datetime.now(UTC),
        payload={"answer": message},
    )


def _build_processor() -> AgentDialogProcessor:
    async def publisher(_event: Any) -> None:
        return None

    def loop_factory() -> AgentLoop:
        registry = ToolRegistry.with_runtime(
            ToolRuntime(
                itinerary_builder=DemoItineraryBuilder(),
                feasibility=StructuralFeasibilityGate(),
            )
        )
        return AgentLoop(decider=ReplayPolicyDecider(), tools=registry)

    return AgentDialogProcessor(
        repository=InMemoryRunRepository(),
        publisher=publisher,
        loop_factory=loop_factory,
    )


def run_scenario(scenario: Scenario) -> dict[str, Any]:
    async def scenario_async() -> dict[str, Any]:
        async def publisher(_event: Any) -> None:
            return None

        def loop_factory() -> AgentLoop:
            registry = ToolRegistry.with_runtime(
                ToolRuntime(
                    itinerary_builder=DemoItineraryBuilder(),
                    feasibility=StructuralFeasibilityGate(),
                )
            )
            return AgentLoop(decider=ReplayPolicyDecider(), tools=registry)

        repository = InMemoryRunRepository()
        processor = AgentDialogProcessor(
            repository=repository,
            publisher=publisher,
            loop_factory=loop_factory,
        )
        violations: list[str] = []
        result: Any = None
        run_id = ""
        for index, message in enumerate(scenario.messages):
            try:
                if index == 0:
                    result = await processor.handle_start(_start_command(message))
                else:
                    result = await processor.handle_resume(_resume_command(run_id, message))
            except Exception as error:  # noqa: BLE001 - harness boundary
                violations.append(f"turn {index} rejected: {error}")
                break
            [run_id] = repository.checkpoints
            if result.stop_reason == "EMITTED":
                break

        if result is None:
            violations.append("no run executed")
            return {"name": scenario.name, "ok": False, "violations": violations}

        if result.stop_reason != scenario.expect_stop:
            violations.append(
                f"stop_reason {result.stop_reason!r} != expected {scenario.expect_stop!r}"
            )
        if scenario.expect_destination is not None:
            slot = result.slots.get("destination")
            if slot.value != scenario.expect_destination or not slot.hard:
                violations.append(
                    f"destination {slot.value!r} ({slot.state.value}) != "
                    f"confirmed {scenario.expect_destination!r}"
                )
        if scenario.expect_infeasible:
            builds = [obs for obs in result.observations if obs.tool == "build_itinerary"]
            if not builds or builds[-1].error_code != "PLANNING_INFEASIBLE":
                violations.append("expected a PLANNING_INFEASIBLE build observation")
        if result.stop_reason == "EMITTED":
            gate = StructuralFeasibilityGate()
            report = await gate(itinerary=result.itinerary, slots={})
            if report.has_blocker:
                violations.append(f"emitted itinerary blocked the gate: {report.violations}")
        failed = [
            obs for obs in result.observations if not obs.ok and obs.error_code == "TOOL_ERROR"
        ]
        if failed:
            violations.append(f"tool handler crashes leaked: {len(failed)}")
        return {
            "name": scenario.name,
            "ok": not violations,
            "violations": violations,
            "stop_reason": result.stop_reason,
            "steps": result.steps,
        }

    return run_async(scenario_async())


def run_all() -> list[dict[str, Any]]:
    return [run_scenario(scenario) for scenario in SCENARIOS]


def main() -> int:
    reports = run_all()
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0 if all(report["ok"] for report in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
