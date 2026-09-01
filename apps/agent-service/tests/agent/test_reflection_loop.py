"""E-1 — the Planning Reflection Loop (T1–T7).

Covers the Phase E acceptance surface:

- T1/T2: the EMITTED gate now consults the Evaluation verdict (S2 fixed).
- T3: the AskingDecider actually READS ``plan_evaluation`` from state and
  changes its decision (Case B) — and skips a doomed structural pass.
- T4: the full closed loop — Evaluation → Reflection → Decision → Replan
  (user constraint change) → rebuild → EMITTED.
- T5: Failure and Quality Feedback are distinct channels.
- T6: the Reflection Budget is bounded (Case D) — a misbehaving decider
  cannot REPLAN without end.
- T7: the LLM decision context (CURRENT STATE) carries the evaluation and
  the reflection budget.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from trip_agent.agent.failure_policy import classify_failure
from trip_agent.agent.feasibility_gate import StructuralFeasibilityGate
from trip_agent.agent.graph import (
    AgentLoop,
    AskingDecider,
    Decision,
    StructuredOutputDecider,
    run_agent,
)
from trip_agent.agent.itinerary_builder import RealItineraryBuilder
from trip_agent.agent.reflection import (
    REFLECTION_EXHAUSTED_ANSWER,
    REFLECTION_MAX_ATTEMPTS,
    reflect_on_evaluation,
)
from trip_agent.agent.state import (
    AgentState,
    ConstraintSlots,
    SlotState,
    agent_state_from_dict,
    agent_state_to_dict,
)
from trip_agent.agent.tools import ToolCall, ToolRegistry, ToolRuntime
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.providers.map import Coordinates, Poi, ProviderSuccess

_SLOTS = (
    ConstraintSlots.empty()
    .fill("destination", "成都", state=SlotState.CONFIRMED)
    .fill("start_date", "2026-10-01", state=SlotState.CONFIRMED)
    .fill("end_date", "2026-10-03", state=SlotState.CONFIRMED)
    .fill("budget", "5000", state=SlotState.CONFIRMED)
)

_BAD_MUST_VISIT_SLOTS = _SLOTS.fill(
    "must_visit", ["不存在的景点"], state=SlotState.CONFIRMED
)


def _poi(provider_id: str, name: str) -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=104.06, latitude=30.67),
        type_name="风景名胜",
        type_code="110000",
        province="四川省",
        city="成都市",
        district="青羊区",
        address=f"{name}地址",
    )


def _mall() -> Poi:
    return Poi(
        provider_id="mall",
        name="成都万象城",
        coordinates=Coordinates(longitude=104.09, latitude=30.66),
        type_name="购物",
        type_code="060000",
        province="四川省",
        city="成都市",
        district="成华区",
        address="成都万象城地址",
    )


class _FakeMapProvider:
    async def search_pois(self, request: object) -> ProviderSuccess:
        return ProviderSuccess(
            data=(_poi("p1", "宽窄巷子"), _poi("p2", "武侯祠"), _mall()),
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
            estimated=False,
        )


class _FakeRouteProvider:
    async def get_route(self, request: object):
        from trip_agent.providers._route_contracts import RoutePlan, RouteStep

        duration = 900 if request.mode == "WALKING" else 1_000
        origin = Coordinates(longitude=104.06, latitude=30.67)
        destination = Coordinates(longitude=104.07, latitude=30.68)
        return ProviderSuccess(
            data=RoutePlan(
                mode=request.mode,
                distance_meters=1_200,
                duration_seconds=duration,
                steps=(
                    RouteStep(
                        instruction=request.mode,
                        distance_meters=1_200,
                        duration_seconds=duration,
                        polyline=(origin, destination),
                    ),
                ),
                polyline=(origin, destination),
                estimated_cost=4.0 if request.mode == "TRANSIT" else None,
                walking_distance_meters=200 if request.mode == "TRANSIT" else None,
                transfer_count=1 if request.mode == "TRANSIT" else None,
            ),
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
            estimated=False,
        )


def _real_builder() -> RealItineraryBuilder:
    provider = AmapPlanningProvider(_FakeMapProvider(), _FakeRouteProvider(), _FakeRouteProvider())
    return RealItineraryBuilder(provider=provider, provider_name="AMAP")


def _registry(builder: object) -> ToolRegistry:
    return ToolRegistry.with_runtime(
        ToolRuntime(itinerary_builder=builder, feasibility=StructuralFeasibilityGate())
    )


async def _capture(loop: AgentLoop, state: AgentState) -> tuple[object, list[AgentState]]:
    states: list[AgentState] = []

    async def sink(snapshot: AgentState) -> None:
        states.append(snapshot)

    result = await run_agent(loop, state, checkpoint_sink=sink)
    return result, states


# ── T1 — P0/S2 regression: hard-validation FAIL must not EMIT ────────────────


def test_t1_needs_repair_is_not_emitted() -> None:
    loop = AgentLoop(decider=AskingDecider(), tools=_registry(_real_builder()))
    result = asyncio.run(run_agent(loop, AgentState(slots=_BAD_MUST_VISIT_SLOTS)))

    assert result.stop_reason != "EMITTED"
    assert result.stop_reason == "WAITING_USER"
    assert result.pending_question is not None
    assert "调整必去地点、日期或预算" in result.pending_question


# ── T2 — Case A regression: a clean candidate still EMITs ────────────────────


def test_t2_clean_candidate_still_emits() -> None:
    loop = AgentLoop(decider=AskingDecider(), tools=_registry(_real_builder()))
    result, states = asyncio.run(_capture(loop, AgentState(slots=_SLOTS)))

    assert result.stop_reason == "EMITTED"
    final = states[-1]
    assert final.reflection_attempts == 0
    assert final.plan_evaluation is not None
    assert final.plan_evaluation.get("status") != "NEEDS_REPAIR"


# ── T3 — Case B: the decider reads the Evaluation and changes behaviour ──────


def test_t3_decider_reads_evaluation_and_skips_doomed_gate() -> None:
    loop = AgentLoop(decider=AskingDecider(), tools=_registry(_real_builder()))
    result, states = asyncio.run(
        _capture(loop, AgentState(slots=_BAD_MUST_VISIT_SLOTS))
    )

    assert result.stop_reason == "WAITING_USER"
    final = states[-1]
    # the Evaluation is readable: the decider's reflection branch acted on it
    assert final.plan_evaluation is not None
    assert final.plan_evaluation.get("status") == "NEEDS_REPAIR"
    assert final.failure_kind == "USER_CONSTRAINT"
    assert final.reflection_attempts == 1
    # the reflection branch fires BEFORE a doomed structural pass
    assert not any(
        obs.tool == "validate_itinerary" for obs in final.observations
    )


# ── T4 — the closed loop: Evaluation → Reflection → Decision → Replan → EMIT ─


def test_t4_reflection_loop_completes_via_user_adjustment() -> None:
    loop = AgentLoop(decider=AskingDecider(), tools=_registry(_real_builder()))
    first, states = asyncio.run(
        _capture(loop, AgentState(slots=_BAD_MUST_VISIT_SLOTS))
    )
    assert first.stop_reason == "WAITING_USER"
    checkpoint = states[-1]

    # Mimic handle_resume (agent_processor.py:293-307): clear the pending
    # question/answer and give the turn a fresh budget.
    resumed = replace(
        checkpoint,
        user_message="预算提高到 9000，去掉不存在的景点",
        pending_question=None,
        pending_options=None,
        pending_expected_type=None,
        pending_call=None,
        stop_reason=None,
        answer=None,
        steps=0,
        turn_baseline_observations=len(checkpoint.observations),
    )
    second, states2 = asyncio.run(_capture(loop, resumed))

    assert second.stop_reason == "EMITTED"
    final = states2[-1]
    # the constraint change reset the reflection budget with the failure memory
    assert final.reflection_attempts == 0
    assert final.plan_evaluation.get("status") != "NEEDS_REPAIR"
    assert any(
        obs.tool == "update_constraints" for obs in final.observations
    )
    assert any(
        obs.tool == "validate_itinerary" and obs.ok for obs in final.observations
    )


# ── T5 — Failure ≠ Quality Feedback ──────────────────────────────────────────


def test_t5_quality_feedback_is_not_a_failure() -> None:
    # A hard-PASS plan with POOR quality: a legitimate state (E-0 Fact C).
    evaluation = {
        "status": "VERIFIED",
        "failures": [],
        "quality": {"verdict": "POOR", "score": 58, "reasons": ["预算利用率偏高（92%）"]},
    }
    # quality never gates the reflection verdict
    assert reflect_on_evaluation(evaluation) == "ACCEPT"
    # quality never feeds the failure classifier
    kind, signature = classify_failure(
        tool="build_itinerary", ok=True, validation_reason_codes=()
    )
    assert kind is None and signature == ""
    # quality round-trips the checkpoint untouched
    state = AgentState(
        slots=_SLOTS,
        plan_evaluation=evaluation,
        reflection_attempts=2,
    )
    restored = agent_state_from_dict(agent_state_to_dict(state))
    assert restored.plan_evaluation == evaluation
    assert restored.reflection_attempts == 2


def test_t5_hard_failure_dominates_quality() -> None:
    # The channels are distinct: GOOD quality does not rescue an unresolved
    # hard-validation FAIL.
    evaluation = {
        "status": "NEEDS_REPAIR",
        "failures": [{"rule_id": "X", "reason_code": "BUDGET_EXCEEDED", "message": "m"}],
        "quality": {"verdict": "GOOD", "score": 92, "reasons": []},
    }
    assert reflect_on_evaluation(evaluation) == "REJECT_HARD"


# ── T6 — Case D: the Reflection Budget is bounded ────────────────────────────


class _AlwaysBuildDecider:
    """A misbehaving decider that never changes constraints — the LLM path
    would be the realistic carrier of this behaviour."""

    async def decide(self, state: AgentState) -> Decision:
        return Decision(thought="keep trying", call=ToolCall("build_itinerary"))


def test_t6_reflection_budget_is_bounded() -> None:
    loop = AgentLoop(decider=_AlwaysBuildDecider(), tools=_registry(_real_builder()))
    result, states = asyncio.run(
        _capture(loop, AgentState(slots=_BAD_MUST_VISIT_SLOTS))
    )

    assert result.stop_reason == "ANSWERED"
    assert result.answer == REFLECTION_EXHAUSTED_ANSWER
    final = states[-1]
    assert final.reflection_attempts == REFLECTION_MAX_ATTEMPTS == 3
    builds = [obs for obs in final.observations if obs.tool == "build_itinerary"]
    assert len(builds) == 3
    # stopped by the reflection budget, not by the step ceiling
    assert result.steps < 8
    assert final.stop_reason is None or final.stop_reason != "CEILING_REACHED"


# ── T7 — P1: decision context (CURRENT STATE) injection contract ─────────────


def test_t7_decision_context_injects_evaluation_and_budget() -> None:
    decider = StructuredOutputDecider(transport=object(), tools=ToolRegistry())
    state = AgentState(
        slots=_SLOTS,
        plan_evaluation={
            "status": "NEEDS_REPAIR",
            "failures": [
                {
                    "rule_id": "MUST_VISIT_COVERAGE",
                    "reason_code": "MUST_VISIT_PLACE_MISSING",
                    "message": "必去地点未被覆盖",
                }
            ],
            "quality": {"verdict": "POOR", "score": 58, "reasons": ["预算利用率偏高"]},
        },
        reflection_attempts=2,
    )
    prompt = decider._prompt(state)
    assert "当前行程评估 (PLAN EVALUATION)" in prompt
    assert "NEEDS_REPAIR" in prompt
    assert "MUST_VISIT_PLACE_MISSING" in prompt
    assert "POOR (score 58)" in prompt
    assert "反思预算 (REFLECTION BUDGET): 2/3" in prompt
    assert "不得以完成姿态结束会话" in prompt

    # no evaluation → stable structure with (无), never a crash
    bare = decider._prompt(AgentState(slots=_SLOTS))
    assert "当前行程评估 (PLAN EVALUATION)" in bare
    assert "(无)" in bare
