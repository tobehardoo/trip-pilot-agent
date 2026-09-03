"""Agent loop behaviour: bounded, fail-closed, and never inventing facts.

These tests use ``run_async`` to match the rest of the suite — the project
runs no pytest-asyncio plugin.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from trip_agent.agent import (
    AgentLoop,
    AgentState,
    AskingDecider,
    ConstraintSlots,
    Decision,
    SlotState,
    ToolCall,
    ToolRegistry,
    ToolRuntime,
    run_agent,
    to_constraint_patch,
    to_trip_fields,
)
from trip_agent.platform_util import run_async
from trip_agent.worker.contracts import Itinerary, ItineraryActivity, ItineraryDay


def _report(has_blocker: bool) -> Any:
    return type("Report", (), {"has_blocker": has_blocker})()


def _demo_itinerary() -> Itinerary:
    start = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    return Itinerary(
        title="测试行程",
        days=(
            ItineraryDay(
                date=start.date(),
                activities=(
                    ItineraryActivity(
                        title="武侯祠",
                        startTime=start,
                        endTime=start.replace(hour=11),
                        estimatedCost=Decimal("0"),
                        source="DEMO",
                    ),
                ),
                transitLegs=(),
            ),
        ),
        estimatedTotalCost=Decimal("0"),
    )


async def _fake_builder(*, slots: Any, trip_id: str | None = None) -> Itinerary:
    del slots, trip_id
    return _demo_itinerary()


def _confirmed_slots() -> ConstraintSlots:
    slots = ConstraintSlots.empty()
    for name in ("destination", "start_date", "end_date"):
        slots = slots.fill(name, "value", state=SlotState.CONFIRMED)
    return slots


class _ScriptedDecider:
    """Replays a fixed decision sequence, then answers."""

    def __init__(self, decisions: list[Decision]) -> None:
        self._pending = list(decisions)

    async def decide(self, state: AgentState) -> Decision:
        if not self._pending:
            return Decision(thought="script exhausted", answer="done")
        return self._pending.pop(0)


class _RepeatingDecider:
    """Never converges — used to prove the ceiling stops the loop."""

    async def decide(self, state: AgentState) -> Decision:
        return Decision(
            thought="keep going",
            call=ToolCall("update_constraints", {"values": {"budget": 100}}),
        )


def test_inferred_slot_is_never_a_hard_constraint() -> None:
    slots = ConstraintSlots.empty().fill("destination", "成都", state=SlotState.INFERRED)
    assert slots.get("destination").filled
    assert not slots.get("destination").hard
    assert "destination" not in slots.confirmed_values()
    assert slots.missing_required() == ("destination", "start_date", "end_date")


def test_confirmed_slot_enters_the_hard_projection() -> None:
    slots = ConstraintSlots.empty().fill("destination", "成都", state=SlotState.CONFIRMED)
    assert slots.confirmed_values()["destination"] == "成都"
    assert slots.missing_required() == ("start_date", "end_date")


def test_promoting_a_slot_to_confirmed_makes_it_hard() -> None:
    slots = ConstraintSlots.empty().fill("destination", "成都", state=SlotState.INFERRED)
    assert "destination" not in slots.confirmed_values()
    assert slots.confirm("destination").confirmed_values()["destination"] == "成都"


def test_asking_decider_stops_to_ask_for_the_first_missing_slot() -> None:
    loop = AgentLoop(decider=AskingDecider(), tools=ToolRegistry.with_runtime(ToolRuntime()))
    result = run_async(run_agent(loop))
    assert result.stop_reason == "WAITING_USER"
    assert result.pending_question == "你想去哪个城市？"
    assert result.answer is None


def test_asking_decider_hands_off_once_required_slots_are_confirmed() -> None:
    loop = AgentLoop(decider=AskingDecider(), tools=ToolRegistry.with_runtime(ToolRuntime()))
    result = run_async(run_agent(loop, AgentState(slots=_confirmed_slots())))
    assert result.answer
    assert result.stop_reason == "ANSWERED"
    assert result.pending_question is None


def test_unknown_tool_is_reported_instead_of_raising() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    result, update = run_async(tools.invoke(ToolCall("does_not_exist"), AgentState()))
    assert not result.ok
    assert result.error_code == "UNKNOWN_TOOL"
    assert update == {}


def test_missing_capability_fails_closed_instead_of_guessing() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    result, _ = run_async(
        tools.invoke(ToolCall("build_itinerary"), AgentState())
    )
    assert not result.ok
    assert result.error_code == "CAPABILITY_MISSING"


def test_update_constraints_keeps_inferred_values_soft() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    result, update = run_async(
        tools.invoke(
            ToolCall("update_constraints", {"values": {"budget": 5000}, "confirmed": False}),
            AgentState(),
        )
    )
    assert result.ok
    slots = update["slots"]
    assert slots.get("budget").state is SlotState.INFERRED
    assert "budget" not in slots.confirmed_values()


def test_update_constraints_ignores_unknown_slot_names() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    result, update = run_async(
        tools.invoke(
            ToolCall("update_constraints", {"values": {"teleportation": True}}),
            AgentState(),
        )
    )
    assert result.ok
    assert "teleportation" not in update["slots"].slots


def test_emit_is_no_longer_a_model_tool() -> None:
    registry = ToolRegistry.with_runtime(ToolRuntime())
    assert "emit_itinerary" not in registry.names()
    assert "build_itinerary" in registry.names()


def test_a_passing_gate_auto_emits_the_candidate() -> None:
    async def gate(**_kwargs: Any) -> Any:
        return _report(has_blocker=False)

    tools = ToolRegistry.with_runtime(
        ToolRuntime(feasibility=gate, itinerary_builder=_fake_builder)
    )
    loop = AgentLoop(
        decider=_ScriptedDecider(
            [
                Decision(thought="build", call=ToolCall("build_itinerary")),
                Decision(thought="gate", call=ToolCall("validate_itinerary")),
            ]
        ),
        tools=tools,
    )
    result = run_async(run_agent(loop, AgentState(slots=_confirmed_slots())))
    assert result.stop_reason == "EMITTED"
    assert result.itinerary is not None
    assert result.itinerary["title"] == "测试行程"
    assert any(obs.tool == "validate_itinerary" and obs.ok for obs in result.observations)


def test_a_blocked_gate_keeps_the_run_going() -> None:
    async def blocked(**_kwargs: Any) -> Any:
        return _report(has_blocker=True)

    tools = ToolRegistry.with_runtime(
        ToolRuntime(feasibility=blocked, itinerary_builder=_fake_builder)
    )
    loop = AgentLoop(
        decider=_ScriptedDecider(
            [
                Decision(thought="build", call=ToolCall("build_itinerary")),
                Decision(thought="gate", call=ToolCall("validate_itinerary")),
                Decision(thought="gate again", call=ToolCall("validate_itinerary")),
            ]
        ),
        tools=tools,
        max_steps=3,
    )
    result = run_async(run_agent(loop, AgentState(slots=_confirmed_slots())))
    assert result.stop_reason == "CEILING_REACHED"
    blocked_observations = [
        obs for obs in result.observations if obs.tool == "validate_itinerary" and not obs.ok
    ]
    assert blocked_observations
    assert blocked_observations[-1].error_code == "FEASIBILITY_BLOCKED"


def test_validate_without_a_candidate_is_refused() -> None:
    async def gate(**_kwargs: Any) -> Any:
        return _report(has_blocker=False)

    tools = ToolRegistry.with_runtime(ToolRuntime(feasibility=gate))
    result, update = run_async(tools.invoke(ToolCall("validate_itinerary"), AgentState()))
    assert not result.ok
    assert result.error_code == "NO_CANDIDATE"
    assert update == {}


def test_build_requires_the_required_slots() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime(itinerary_builder=_fake_builder))
    result, _ = run_async(tools.invoke(ToolCall("build_itinerary"), AgentState()))
    assert not result.ok
    assert result.error_code == "INCOMPLETE_CONSTRAINTS"
    result, update = run_async(
        tools.invoke(ToolCall("build_itinerary"), AgentState(slots=_confirmed_slots()))
    )
    assert result.ok
    assert update["candidate_itinerary"]["title"] == "测试行程"


def test_declared_strategy_is_recorded_in_the_state() -> None:
    class _StrategicDecider:
        async def decide(self, state: AgentState) -> Decision:
            if not state.observations:
                return Decision(
                    thought="trigger the pipeline first",
                    call=ToolCall("build_itinerary"),
                    strategy="BUILD",
                )
            return Decision(
                thought="ask",
                call=ToolCall("ask_user", {"question": "在吗？"}),
                strategy="CLARIFY",
            )

    states: list[AgentState] = []

    async def sink(state: AgentState) -> None:
        states.append(state)

    loop = AgentLoop(decider=_StrategicDecider(), tools=ToolRegistry.with_runtime(ToolRuntime()))
    result = run_async(run_agent(loop, checkpoint_sink=sink))
    assert result.stop_reason == "WAITING_USER"
    assert states[-1].strategy == "CLARIFY"


def test_the_deterministic_fallback_declares_its_strategy() -> None:
    states: list[AgentState] = []

    async def sink(state: AgentState) -> None:
        states.append(state)

    loop = AgentLoop(decider=AskingDecider(), tools=ToolRegistry.with_runtime(ToolRuntime()))
    run_async(run_agent(loop, checkpoint_sink=sink))
    assert states[-1].strategy == "CLARIFY"


def test_loop_stops_at_the_step_ceiling() -> None:
    loop = AgentLoop(
        decider=_RepeatingDecider(),
        tools=ToolRegistry.with_runtime(ToolRuntime()),
        max_steps=3,
    )
    result = run_async(run_agent(loop))
    assert result.steps == 3
    assert result.stop_reason == "CEILING_REACHED"


def test_projection_maps_confirmed_slots_onto_trip_constraint_fields() -> None:
    slots = (
        ConstraintSlots.empty()
        .fill("destination", "成都", state=SlotState.CONFIRMED)
        .fill("budget", 5000, state=SlotState.CONFIRMED)
        .fill("pace", "RELAXED", state=SlotState.CONFIRMED)
        .fill("must_visit", ("武侯祠",), state=SlotState.CONFIRMED)
    )
    assert to_constraint_patch(slots) == {
        "budget_amount": 5000,
        "pace": "RELAXED",
        "must_visit_places": ("武侯祠",),
    }
    assert to_trip_fields(slots) == {"destination": "成都"}


def test_projection_never_leaks_inferred_values() -> None:
    slots = ConstraintSlots.empty().fill("budget", 5000, state=SlotState.INFERRED)
    assert to_constraint_patch(slots) == {}
    assert to_trip_fields(slots) == {}


def test_tool_call_ceiling_is_enforced() -> None:
    loop = AgentLoop(
        decider=_RepeatingDecider(),
        tools=ToolRegistry.with_runtime(ToolRuntime()),
        max_steps=50,
        max_tool_calls=2,
    )
    result = run_async(run_agent(loop))
    assert len(result.observations) == 2
    assert result.stop_reason == "CEILING_REACHED"
