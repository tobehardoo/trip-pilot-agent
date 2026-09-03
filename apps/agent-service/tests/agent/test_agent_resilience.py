"""Batch-A resilience and slot-lifecycle behaviour (P1.1–P1.5).

Covers: model transport failures degrade deterministically (D1), tool handler
exceptions become observations (D2), ask_user carries structured options,
confirmed provenance is decided by code from user evidence (D5), and the
slot state machine records rejections and audited overrides.

These tests use ``run_async`` to match the rest of the suite — the project
runs no pytest-asyncio plugin.
"""

from __future__ import annotations

from typing import Any

import httpx

from trip_agent.agent import (
    AgentLoop,
    AgentState,
    AskingDecider,
    ConstraintSlots,
    Decision,
    SlotState,
    StructuredOutputDecider,
    ToolCall,
    ToolRegistry,
    ToolRuntime,
    run_agent,
)
from trip_agent.platform_util import run_async


def _confirmed_slots() -> ConstraintSlots:
    slots = ConstraintSlots.empty()
    for name in ("destination", "start_date", "end_date"):
        slots = slots.fill(name, "value", state=SlotState.CONFIRMED)
    return slots

DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
}


class _TransportErroring:
    """Transport that always raises the given error."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def extract(
        self,
        *,
        content: str,
        json_schema: dict[str, Any],
        timeout_seconds: float,
    ) -> object:
        raise self._error


class _TransportGarbage:
    """Transport that returns unparsable output."""

    async def extract(
        self,
        *,
        content: str,
        json_schema: dict[str, Any],
        timeout_seconds: float,
    ) -> object:
        return "not-json-at-all"


def _decider(transport: Any) -> StructuredOutputDecider:
    return StructuredOutputDecider(
        transport=transport,
        tools=ToolRegistry.with_runtime(ToolRuntime()),
    )


# ── P1.1 / D1: transport failures never break the run ──────────────


def test_model_timeout_degrades_to_deterministic_clarification() -> None:
    decider = _decider(_TransportErroring(httpx.TimeoutException("timed out")))
    decision = run_async(decider.decide(AgentState()))
    assert decision.answer is None
    assert decision.call is not None
    assert decision.call.tool == "ask_user"
    assert decision.call.args["question"] == "你想去哪个城市？"


def test_model_http_error_degrades_instead_of_raising() -> None:
    decider = _decider(_TransportErroring(httpx.ConnectError("refused")))
    decision = run_async(decider.decide(AgentState()))
    assert decision.call is not None and decision.call.tool == "ask_user"


def test_model_timeout_with_missing_slots_asks_for_the_first_missing() -> None:
    decider = _decider(_TransportErroring(httpx.ReadTimeout("read timed out")))
    slots = ConstraintSlots.empty().fill(
        "destination", "成都", state=SlotState.CONFIRMED
    )
    decision = run_async(decider.decide(AgentState(slots=slots)))
    assert decision.call is not None
    assert decision.call.args["question"] == "行程从哪天开始？"


def test_unparsable_output_also_uses_the_deterministic_fallback() -> None:
    decider = _decider(_TransportGarbage())
    decision = run_async(decider.decide(AgentState()))
    assert decision.call is not None
    assert decision.call.args["question"] == "你想去哪个城市？"


def test_a_run_with_a_failing_transport_still_converges() -> None:
    loop = AgentLoop(
        decider=_decider(_TransportErroring(httpx.TimeoutException("timed out"))),
        tools=ToolRegistry.with_runtime(ToolRuntime()),
    )
    result = run_async(run_agent(loop))
    assert result.stop_reason == "WAITING_USER"
    assert result.pending_question == "你想去哪个城市？"
    assert result.answer is None


# ── P1.2 / D2: handler exceptions become observations ──────────────


class _ExplodingProfileStore:
    """A profile store whose writes raise — proves handler exceptions surface."""

    async def propose(self, *__args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("store exploded")

    async def confirm(self, *__args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("store exploded")

    async def revoke(self, *__args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("store exploded")


def test_handler_exception_becomes_a_tool_error_not_a_crash() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime(profile_store=_ExplodingProfileStore()))
    result, update = run_async(
        tools.invoke(
            ToolCall(
                "update_preferences",
                {"proposals": [{"category": "DIETARY", "value": "川菜"}]},
            ),
            AgentState(user_id="u1", slots=_confirmed_slots()),
        )
    )
    assert not result.ok
    assert result.error_code == "TOOL_ERROR"
    assert update == {}


def test_a_run_continues_after_a_handler_exception() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime(profile_store=_ExplodingProfileStore()))
    loop = AgentLoop(
        decider=_ScriptedPreferenceThenAsk(),
        tools=tools,
    )
    result = run_async(run_agent(loop, AgentState(user_id="u1", slots=_confirmed_slots())))
    failed = [obs for obs in result.observations if obs.tool == "update_preferences"]
    assert failed and not failed[0].ok and failed[0].error_code == "TOOL_ERROR"
    assert result.stop_reason == "WAITING_USER"


class _ScriptedPreferenceThenAsk:
    async def decide(self, state: AgentState) -> Decision:
        if not state.observations:
            return Decision(
                thought="try the tool",
                call=ToolCall(
                    "update_preferences",
                    {"proposals": [{"category": "DIETARY", "value": "川菜"}]},
                ),
            )
        return Decision(thought="ask instead", call=ToolCall("ask_user", {"question": "在吗？"}))


# ── P1.3: ask_user with options and expected_type ──────────────────


def test_ask_user_carries_options_and_expected_type() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    result, update = run_async(
        tools.invoke(
            ToolCall(
                "ask_user",
                {
                    "question": "想去哪个城市？",
                    "options": ["成都", "北京"],
                    "expected_type": "choice",
                },
            ),
            AgentState(),
        )
    )
    assert result.ok
    assert update["pending_question"] == "想去哪个城市？"
    assert update["pending_options"] == ("成都", "北京")
    assert update["pending_expected_type"] == "choice"


def test_ask_user_without_options_keeps_them_unset() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    _, update = run_async(tools.invoke(ToolCall("ask_user", {"question": "在吗？"}), AgentState()))
    assert update["pending_options"] is None
    assert update["pending_expected_type"] is None


def test_ask_user_rejects_malformed_options() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    result, _ = run_async(
        tools.invoke(
            ToolCall("ask_user", {"question": "去哪？", "options": ["成都", ""]}),
            AgentState(),
        )
    )
    assert not result.ok
    assert result.error_code == "INVALID_OPTIONS"


def test_ask_user_rejects_too_many_options() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    result, _ = run_async(
        tools.invoke(
            ToolCall("ask_user", {"question": "去哪？", "options": [f"c{i}" for i in range(11)]}),
            AgentState(),
        )
    )
    assert not result.ok
    assert result.error_code == "INVALID_OPTIONS"


def test_ask_user_rejects_unknown_expected_type() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    result, _ = run_async(
        tools.invoke(
            ToolCall("ask_user", {"question": "去哪？", "expected_type": "emoji"}),
            AgentState(),
        )
    )
    assert not result.ok
    assert result.error_code == "INVALID_EXPECTED_TYPE"


# ── P1.4 / D5: confirmed is decided by code, not by the LLM ────────


def test_value_is_confirmed_only_when_user_evidence_contains_it() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    result, update = run_async(
        tools.invoke(
            ToolCall(
                "update_constraints",
                {"values": {"destination": "成都"}, "evidence": "十一我想去成都玩"},
            ),
            AgentState(),
        )
    )
    assert result.ok
    slots = update["slots"]
    assert slots.get("destination").state is SlotState.CONFIRMED
    assert slots.get("destination").verified_by == "rule:evidence-match"


def test_value_without_matching_evidence_stays_inferred() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    _, update = run_async(
        tools.invoke(
            ToolCall(
                "update_constraints",
                {"values": {"destination": "成都"}, "evidence": "随便 somewhere else"},
            ),
            AgentState(),
        )
    )
    assert update["slots"].get("destination").state is SlotState.INFERRED


def test_value_without_evidence_stays_inferred() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    _, update = run_async(
        tools.invoke(
            ToolCall("update_constraints", {"values": {"destination": "成都"}}),
            AgentState(),
        )
    )
    assert update["slots"].get("destination").state is SlotState.INFERRED


def test_the_legacy_self_confirmed_flag_is_ignored() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    _, update = run_async(
        tools.invoke(
            ToolCall("update_constraints", {"values": {"destination": "成都"}, "confirmed": True}),
            AgentState(),
        )
    )
    assert update["slots"].get("destination").state is SlotState.INFERRED


def test_numeric_value_confirms_against_numeric_evidence() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    _, update = run_async(
        tools.invoke(
            ToolCall(
                "update_constraints",
                {"values": {"budget": 5000}, "evidence": "预算5000以内"},
            ),
            AgentState(),
        )
    )
    assert update["slots"].get("budget").state is SlotState.CONFIRMED


def test_changing_a_confirmed_value_creates_an_override_audit_chain() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    _, first = run_async(
        tools.invoke(
            ToolCall(
                "update_constraints",
                {"values": {"destination": "成都"}, "evidence": "去成都"},
            ),
            AgentState(),
        )
    )
    _, second = run_async(
        tools.invoke(
            ToolCall(
                "update_constraints",
                {"values": {"destination": "北京"}, "evidence": "还是改去北京吧"},
            ),
            AgentState(first["slots"]),
        )
    )
    slot = second["slots"].get("destination")
    assert slot.state is SlotState.USER_OVERRIDE
    assert slot.value == "北京"
    assert slot.override_of == "成都"
    assert slot.hard


# ── P1.5: REJECTED / USER_OVERRIDE slot lifecycle ──────────────────


def test_rejected_slot_keeps_the_value_but_is_never_hard() -> None:
    slots = ConstraintSlots.empty().fill("destination", "成都", state=SlotState.INFERRED)
    rejected = slots.reject("destination", evidence="不想去成都")
    slot = rejected.get("destination")
    assert slot.state is SlotState.REJECTED
    assert slot.value == "成都"
    assert not slot.hard
    assert "destination" in rejected.missing_required()


def test_rejection_is_a_user_action_with_provenance() -> None:
    rejected = ConstraintSlots.empty().reject("destination", evidence="别提成都")
    slot = rejected.get("destination")
    assert slot.verified_by == "user"
    assert slot.updated_at


def test_update_constraints_refuses_a_rejected_value_even_with_evidence() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    slots = (
        ConstraintSlots.empty()
        .fill("destination", "成都", state=SlotState.INFERRED)
        .reject("destination", evidence="不想去成都")
    )
    result, update = run_async(
        tools.invoke(
            ToolCall(
                "update_constraints",
                {"values": {"destination": "成都"}, "evidence": "去成都"},
            ),
            AgentState(slots),
        )
    )
    assert result.ok
    slot = update["slots"].get("destination")
    assert slot.state is SlotState.REJECTED
    assert result.data["refused"] == ["destination"]


def test_rejection_records_the_supplied_value_and_blocks_reproposal() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    result, update = run_async(
        tools.invoke(
            ToolCall(
                "update_constraints",
                {"rejections": {"destination": "成都"}, "evidence": "不想去成都"},
            ),
            AgentState(),
        )
    )
    assert result.ok
    slot = update["slots"].get("destination")
    assert slot.state is SlotState.REJECTED
    assert slot.value == "成都"

    reproposal, _ = run_async(
        tools.invoke(
            ToolCall(
                "update_constraints",
                {"values": {"destination": "成都"}, "evidence": "还是去成都吧"},
            ),
            AgentState(update["slots"]),
        )
    )
    assert reproposal.ok
    assert reproposal.data["refused"] == ["destination"]


def test_a_rejected_slot_accepts_a_genuinely_new_value() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime())
    slots = ConstraintSlots.empty().reject("destination", evidence="不想去成都")
    _, update = run_async(
        tools.invoke(
            ToolCall(
                "update_constraints",
                {"values": {"destination": "北京"}, "evidence": "那就去北京"},
            ),
            AgentState(slots=slots),
        )
    )
    slot = update["slots"].get("destination")
    assert slot.state is SlotState.CONFIRMED
    assert slot.value == "北京"


def test_user_override_is_hard_and_audited() -> None:
    slots = ConstraintSlots.empty().fill("destination", "成都", state=SlotState.CONFIRMED)
    overridden = slots.override("destination", "北京")
    slot = overridden.get("destination")
    assert slot.state is SlotState.USER_OVERRIDE
    assert slot.hard
    assert slot.override_of == "成都"
    assert slot.verified_by == "user"
    assert slot.updated_at


def test_rejected_values_are_listed_for_the_prompt() -> None:
    slots = ConstraintSlots.empty().fill("destination", "成都", state=SlotState.INFERRED)
    rejected = slots.reject("destination", evidence="不去")
    assert rejected.rejected_values() == {"destination": "成都"}
    assert ConstraintSlots.empty().rejected_values() == {}


def test_confirm_preserves_audit_metadata() -> None:
    slots = ConstraintSlots.empty().fill("destination", "成都", state=SlotState.INFERRED)
    overridden = slots.override("destination", "北京")
    confirmed = overridden.confirm("destination")
    slot = confirmed.get("destination")
    assert slot.state is SlotState.CONFIRMED
    assert slot.verified_by == "user"
    assert slot.override_of == "成都"


def test_asking_decider_still_runs_end_to_end_without_keys() -> None:
    loop = AgentLoop(decider=AskingDecider(), tools=ToolRegistry.with_runtime(ToolRuntime()))
    result = run_async(run_agent(loop))
    assert result.stop_reason == "WAITING_USER"
    assert result.pending_question == "你想去哪个城市？"
