"""Batch-B persistence: state serialization, checkpoint sink, run repository.

Unit tests cover the versioned AgentState round-trip, the streaming
``checkpoint_sink`` on ``run_agent`` and the per-run recorder against a fake
repository.  SQL integration tests follow the repository convention: they
run against a real PostgreSQL gated on ``KNOWLEDGE_TEST_DATABASE_URL`` and
skip when it is unset.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from trip_agent.agent import (
    AgentLoop,
    AgentRunStarted,
    AgentState,
    AskingDecider,
    ConstraintSlots,
    Decision,
    PsycopgAgentRunRepository,
    SlotState,
    ToolCall,
    ToolObservation,
    ToolRegistry,
    ToolRuntime,
    agent_state_from_dict,
    agent_state_to_dict,
    run_agent,
    status_for_stop_reason,
)
from trip_agent.agent.persistence import AgentRunRecorder
from trip_agent.platform_util import run_async


def _sample_slots() -> ConstraintSlots:
    return (
        ConstraintSlots.empty()
        .fill(
            "destination",
            "成都",
            state=SlotState.CONFIRMED,
            evidence="去成都",
            verified_by="rule:evidence-match",
        )
        .fill("budget", 5000, state=SlotState.INFERRED, evidence="大概五千")
        .reject("pace", value="紧凑", evidence="不要赶路")
        .override("travelers", "2大1小", evidence="两个大人一个小孩")
    )


def _sample_state() -> AgentState:
    return AgentState(
        slots=_sample_slots(),
        observations=(
            ToolObservation(
                tool="update_constraints",
                ok=True,
                summary="updated",
                data={"applied": ["destination"]},
            ),
            ToolObservation(
                tool="build_itinerary",
                ok=False,
                summary="required slots missing",
                data=None,
                error_code="INCOMPLETE_CONSTRAINTS",
            ),
        ),
        pending_question="行程从哪天开始？",
        pending_options=("10月1日", "10月2日"),
        pending_expected_type="date",
        pending_call=ToolCall("update_constraints", {"values": {"destination": "成都"}}),
        steps=5,
        stop_reason="WAITING_USER",
    )


# ── serialization round-trip (P1.7) ─────────────────────────────────


def test_state_round_trip_preserves_the_working_memory() -> None:
    state = _sample_state()
    restored = agent_state_from_dict(agent_state_to_dict(state))
    assert restored == state


def test_round_trip_keeps_all_five_slot_states() -> None:
    restored = agent_state_from_dict(agent_state_to_dict(AgentState(slots=_sample_slots())))
    slots = restored.slots
    assert slots.get("accommodation").state is SlotState.UNKNOWN
    assert slots.get("budget").state is SlotState.INFERRED
    assert slots.get("destination").state is SlotState.CONFIRMED
    assert slots.get("destination").verified_by == "rule:evidence-match"
    assert slots.get("pace").state is SlotState.REJECTED
    assert slots.get("pace").value == "紧凑"
    assert slots.get("travelers").state is SlotState.USER_OVERRIDE
    assert slots.get("travelers").override_of is None


def test_non_json_payload_degrades_to_text_instead_of_failing() -> None:
    exotic = object()
    state = AgentState(
        observations=(
            ToolObservation(tool="validate_itinerary", ok=True, summary="report", data=exotic),
        )
    )
    restored = agent_state_from_dict(agent_state_to_dict(state))
    assert restored.observations[0].data == str(exotic)


def test_unknown_checkpoint_version_is_refused() -> None:
    with pytest.raises(ValueError, match="checkpoint version"):
        agent_state_from_dict({"version": 99})


# ── streaming checkpoint sink (P1.7) ────────────────────────────────


class _ScriptedSearchThenAsk:
    async def decide(self, state: AgentState) -> Decision:
        if not state.observations:
            return Decision(
                thought="try the tool",
                call=ToolCall("update_constraints", {"values": {"destination": "成都"}}),
            )
        return Decision(thought="ask instead", call=ToolCall("ask_user", {"question": "在吗？"}))


def test_checkpoint_sink_streams_the_full_state_after_each_node() -> None:
    states: list[AgentState] = []

    async def sink(state: AgentState) -> None:
        states.append(state)

    loop = AgentLoop(
        decider=_ScriptedSearchThenAsk(),
        tools=ToolRegistry.with_runtime(ToolRuntime()),
    )
    result = run_async(run_agent(loop, checkpoint_sink=sink))

    assert len(states) >= 3
    last = states[-1]
    assert last.stop_reason == result.stop_reason == "WAITING_USER"
    assert last.pending_question == result.pending_question
    assert last.observations == result.observations
    sizes = [len(state.observations) for state in states]
    assert sizes == sorted(sizes), "observations must grow monotonically"


# ── the per-run recorder against a fake repository ──────────────────


class FakeRepository:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.checkpoints: list[AgentState] = []
        self.finished: dict[str, Any] | None = None
        self.existing: dict[str, str] = {}

    async def start_run(
        self, *, run_id: str, command_event_id: str | None, trip_id: str | None
    ) -> AgentRunStarted:
        if command_event_id and command_event_id in self.existing:
            return AgentRunStarted(run_id=self.existing[command_event_id], created=False)
        if command_event_id:
            self.existing[command_event_id] = run_id
        return AgentRunStarted(run_id=run_id, created=True)

    async def record_step(
        self, *, run_id: str, seq: int, kind: str, tool: str | None, payload: dict[str, Any]
    ) -> None:
        self.steps.append({"run_id": run_id, "seq": seq, "kind": kind, "tool": tool, **payload})

    async def save_checkpoint(self, *, run_id: str, state: AgentState) -> None:
        self.checkpoints.append(state)

    async def finish_run(self, **kwargs: Any) -> None:
        self.finished = kwargs


def test_recorder_refuses_state_before_start() -> None:
    recorder = AgentRunRecorder(FakeRepository(), run_id="run-1")
    with pytest.raises(RuntimeError, match="start"):
        run_async(recorder.on_state(AgentState()))


def test_recorder_records_only_new_observations() -> None:
    repository = FakeRepository()
    recorder = AgentRunRecorder(repository, run_id="run-1", command_event_id="cmd-1")
    assert run_async(recorder.start()).created is True

    first = AgentState(
        observations=(
            ToolObservation(tool="update_constraints", ok=True, summary="updated", data=None),
        )
    )
    run_async(recorder.on_state(first))
    second = AgentState(
        observations=(
            first.observations[0],
            ToolObservation(tool="ask_user", ok=True, summary="在吗？", data=None),
        )
    )
    run_async(recorder.on_state(second))

    assert [step["seq"] for step in repository.steps] == [0, 1]
    assert [step["tool"] for step in repository.steps] == ["update_constraints", "ask_user"]
    assert repository.steps[0]["kind"] == "TOOL_OBSERVATION"
    assert repository.checkpoints == [first, second]


def test_recorder_surfaces_command_deduplication() -> None:
    repository = FakeRepository()
    first = AgentRunRecorder(repository, run_id="run-1", command_event_id="cmd-1")
    second = AgentRunRecorder(repository, run_id="run-2", command_event_id="cmd-1")
    assert run_async(first.start()).created is True
    duplicate = run_async(second.start())
    assert duplicate.created is False
    assert duplicate.run_id == "run-1"


def test_recorder_finish_maps_stop_reason_to_status() -> None:
    repository = FakeRepository()
    recorder = AgentRunRecorder(repository, run_id="run-1")
    run_async(recorder.start())
    loop = AgentLoop(decider=AskingDecider(), tools=ToolRegistry.with_runtime(ToolRuntime()))
    run_async(recorder.finish(run_async(run_agent(loop))))
    assert repository.finished is not None
    assert repository.finished["status"] == "WAITING_USER"


def test_status_mapping_covers_the_loop_stop_reasons() -> None:
    assert status_for_stop_reason("WAITING_USER") == "WAITING_USER"
    assert status_for_stop_reason("EMITTED") == "COMPLETED"
    assert status_for_stop_reason("ANSWERED") == "COMPLETED"
    assert status_for_stop_reason("CEILING_REACHED") == "STOPPED"
    assert status_for_stop_reason("LLM_BUDGET_EXHAUSTED") == "STOPPED"
    assert status_for_stop_reason(None) == "STOPPED"
    assert status_for_stop_reason("SOMETHING_NEW") == "STOPPED"


# ── SQL integration (gated on a real PostgreSQL) ────────────────────


def database_url() -> str:
    value = os.environ.get("KNOWLEDGE_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("KNOWLEDGE_TEST_DATABASE_URL is not configured")
    return value


@pytest.fixture()
def agent_tables() -> Iterator[PsycopgAgentRunRepository]:
    url = database_url()
    repository = PsycopgAgentRunRepository(url)
    asyncio.run(repository.migrate())
    asyncio.run(repository.migrate())  # migration idempotency is part of the contract
    with psycopg.connect(url) as connection:
        connection.execute(
            "TRUNCATE agent.agent_checkpoint, agent.agent_step, agent.agent_run CASCADE"
        )
    yield repository


def test_start_run_is_idempotent_per_command_event(
    agent_tables: PsycopgAgentRunRepository,
) -> None:
    repository = agent_tables
    first = asyncio.run(
        repository.start_run(run_id="run-1", command_event_id="cmd-1", trip_id="trip-1")
    )
    assert first == AgentRunStarted(run_id="run-1", created=True)

    duplicate = asyncio.run(
        repository.start_run(run_id="run-2", command_event_id="cmd-1", trip_id="trip-1")
    )
    assert duplicate.created is False
    assert duplicate.run_id == "run-1"

    other = asyncio.run(
        repository.start_run(run_id="run-3", command_event_id="cmd-2", trip_id="trip-1")
    )
    assert other.created is True

    anonymous = asyncio.run(
        repository.start_run(run_id="run-4", command_event_id=None, trip_id=None)
    )
    assert anonymous.created is True


def test_record_step_is_idempotent_per_seq(agent_tables: PsycopgAgentRunRepository) -> None:
    repository = agent_tables
    asyncio.run(repository.start_run(run_id="run-1", command_event_id=None, trip_id=None))
    for _ in range(2):  # a redelivered step must not create a second row
        asyncio.run(
            repository.record_step(
                run_id="run-1",
                seq=0,
                kind="TOOL_OBSERVATION",
                tool="update_constraints",
                payload={"ok": True, "summary": "updated"},
            )
        )
    asyncio.run(
        repository.record_step(
            run_id="run-1", seq=1, kind="TOOL_OBSERVATION", tool="ask_user", payload={}
        )
    )
    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        rows = connection.execute(
            "SELECT seq, tool, payload FROM agent.agent_step "
            "WHERE run_id = 'run-1' ORDER BY seq"
        ).fetchall()
    assert [(row["seq"], row["tool"]) for row in rows] == [
        (0, "update_constraints"),
        (1, "ask_user"),
    ]
    assert rows[0]["payload"]["summary"] == "updated"


def test_checkpoint_round_trip(agent_tables: PsycopgAgentRunRepository) -> None:
    repository = agent_tables
    asyncio.run(repository.start_run(run_id="run-1", command_event_id=None, trip_id=None))
    state = _sample_state()
    asyncio.run(repository.save_checkpoint(run_id="run-1", state=state))
    assert asyncio.run(repository.load_checkpoint("run-1")) == state
    assert asyncio.run(repository.checkpoint_updated_at("run-1")) is not None
    assert asyncio.run(repository.checkpoint_updated_at("missing-run")) is None
    assert asyncio.run(repository.load_checkpoint("missing-run")) is None


def test_finish_run_persists_the_outcome(agent_tables: PsycopgAgentRunRepository) -> None:
    repository = agent_tables
    asyncio.run(repository.start_run(run_id="run-1", command_event_id="cmd-9", trip_id="trip-9"))
    asyncio.run(
        repository.finish_run(
            run_id="run-1",
            status="WAITING_USER",
            stop_reason="WAITING_USER",
            answer=None,
            pending_question="在吗？",
        )
    )
    record = asyncio.run(repository.load_run("run-1"))
    assert record is not None
    assert record.status == "WAITING_USER"
    assert record.stop_reason == "WAITING_USER"
    assert record.pending_question == "在吗？"
    assert record.command_event_id == "cmd-9"
    assert record.trip_id == "trip-9"
    assert asyncio.run(repository.load_run("missing-run")) is None
