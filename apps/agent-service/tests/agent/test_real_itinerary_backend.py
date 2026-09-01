"""V3 C-1 — the dialog agent's build_itinerary uses the REAL planning backend.

Before this cut the production ToolRuntime wired DemoItineraryBuilder →
DemoPlanningProvider (placeholder activities).  Now the same slot
projection runs the real deterministic pipeline (AMap facts, real
transport/cost decisions, DecisionTrace) and carries a hard-validation
summary; an infeasible command stops the run instead of retrying to the
step ceiling (a deterministic input cannot succeed on retry).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest import mock

from trip_agent.agent import (
    AgentLoop,
    AgentState,
    AskingDecider,
    ConstraintSlots,
    RealItineraryBuilder,
    SlotState,
    StructuralFeasibilityGate,
    ToolCall,
    ToolRegistry,
    ToolRuntime,
    run_agent,
)
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.providers.map import (
    Coordinates,
    Poi,
    ProviderSuccess,
)
from trip_agent.worker.contracts import Itinerary

_SLOTS = (
    ConstraintSlots.empty()
    .fill("destination", "成都", state=SlotState.CONFIRMED)
    .fill("start_date", "2026-10-01", state=SlotState.CONFIRMED)
    .fill("end_date", "2026-10-03", state=SlotState.CONFIRMED)
    .fill("budget", "5000", state=SlotState.CONFIRMED)
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


def test_real_backend_produces_a_real_amap_itinerary() -> None:
    built = asyncio.run(_real_builder()(slots=_SLOTS))

    assert built.provider_name == "AMAP"
    assert all(
        activity.source == "AMAP"
        for day in built.itinerary.days
        for activity in day.activities
        if activity.source is not None
    )
    assert built.feasibility is not None
    assert built.feasibility["status"] in {"VERIFIED", "UNVERIFIED", "NEEDS_REPAIR"}
    assert all(
        failure["rule_id"] and failure["reason_code"]
        for failure in built.feasibility["failures"]
    )


def test_real_backend_run_emits_a_real_itinerary() -> None:
    loop = AgentLoop(
        decider=AskingDecider(), tools=_registry(_real_builder())
    )
    result = asyncio.run(run_agent(loop, AgentState(slots=_SLOTS)))

    assert result.stop_reason == "EMITTED"
    assert result.itinerary is not None
    activities = [
        activity
        for day in result.itinerary["days"]
        for activity in day["activities"]
    ]
    assert activities, "a real plan places real activities"
    assert all(activity["source"] == "AMAP" for activity in activities)
    drafted = next(obs for obs in result.observations if obs.tool == "build_itinerary")
    assert "via AMAP" in drafted.summary


def test_real_backend_run_surfaces_the_hard_validation_summary() -> None:
    loop = AgentLoop(
        decider=AskingDecider(), tools=_registry(_real_builder())
    )
    result = asyncio.run(run_agent(loop, AgentState(slots=_SLOTS)))

    drafted = next(obs for obs in result.observations if obs.tool == "build_itinerary")
    assert drafted.ok
    assert "hard validation" in drafted.summary


def test_provider_raised_infeasible_stops_the_run() -> None:
    """A provider-raised infeasible (e.g. a structured must-visit that can
    never be pinned) is deterministic — the handler stops the run with the
    conflict instead of burning the step budget on identical retries."""
    from trip_agent.domain.planning.protocols import (
        OptimizationConflict,
        PlanningInfeasibleError,
    )

    class _InfeasibleBuilder:
        async def __call__(self, *, slots: object, trip_id: object) -> Itinerary:
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MUST_VISIT_UNAVAILABLE",
                        "所选必去地点不是可安排的景点",
                        ("不存在的景点",),
                    ),
                ),
                relaxations=(),
            )

    registry = _registry(_InfeasibleBuilder())
    result, update = asyncio.run(
        registry.invoke(ToolCall("build_itinerary"), AgentState(slots=_SLOTS))
    )
    assert not result.ok
    assert result.error_code == "PLANNING_INFEASIBLE"
    assert result.summary == "所选必去地点不是可安排的景点"
    # the tool reports; the decider decides — no stop stolen from policy
    assert update == {}

    loop = AgentLoop(decider=AskingDecider(), tools=registry)
    run_result = asyncio.run(run_agent(loop, AgentState(slots=_SLOTS)))
    # V3 C-4: the deterministic decider asks the user to adjust instead of
    # burning the ceiling on identical retries
    assert run_result.stop_reason == "WAITING_USER"
    assert run_result.pending_question is not None
    assert "无法在当前约束下生成" in run_result.pending_question
    assert "所选必去地点不是可安排的景点" in run_result.pending_question


def test_text_must_visit_conflict_is_not_emitted() -> None:
    """E-1 P0 (S2 regression): a text must-visit that cannot be covered must
    NOT ride to EMITTED on a structural-gate pass.  The hard-validation
    verdict (NEEDS_REPAIR with an unresolved failure) rejects the candidate:
    the run asks the user to adjust instead of emitting it."""
    slots = _SLOTS.fill("must_visit", ["不存在的景点"], state=SlotState.CONFIRMED)
    loop = AgentLoop(decider=AskingDecider(), tools=_registry(_real_builder()))
    result = asyncio.run(run_agent(loop, AgentState(slots=slots)))

    assert result.stop_reason != "EMITTED"
    assert result.stop_reason == "WAITING_USER"
    assert result.pending_question is not None
    assert "调整必去地点、日期或预算" in result.pending_question
    drafted = next(obs for obs in result.observations if obs.tool == "build_itinerary")
    assert "hard validation NEEDS_REPAIR (1 failing rules)" in drafted.summary


def test_demo_builder_still_returns_a_plain_itinerary() -> None:
    """Compatibility: the demo builder keeps its legacy return shape."""
    from trip_agent.agent import DemoItineraryBuilder

    built = asyncio.run(DemoItineraryBuilder()(slots=_SLOTS))
    assert isinstance(built, Itinerary)


def test_tool_runtime_mode_selection_demo_vs_real(monkeypatch) -> None:
    """The production assembly picks the backend by PROVIDER_MODE; a missing
    key in a real mode degrades to demo instead of crashing the dialog."""
    from trip_agent.agent.itinerary_builder import (
        DemoItineraryBuilder,
        RealItineraryBuilder,
    )
    from trip_agent.worker.agent_processor import _itinerary_builder_for_mode

    with mock.patch.dict("os.environ", {"PROVIDER_MODE": "DEMO_ONLY"}):
        monkeypatch.setattr(
            "trip_agent.worker.agent_processor._REAL_BACKEND_CACHE", {}
        )
        assert isinstance(_itinerary_builder_for_mode(), DemoItineraryBuilder)

    env = {
        "PROVIDER_MODE": "REAL_ONLY",
        "AMAP_WEB_SERVICE_KEY": "test-key",
    }
    with mock.patch.dict("os.environ", env, clear=False):
        monkeypatch.setattr(
            "trip_agent.worker.agent_processor._REAL_BACKEND_CACHE", {}
        )
        builder = _itinerary_builder_for_mode()
        assert isinstance(builder, RealItineraryBuilder)


def test_real_run_populates_goal_and_decision_memory() -> None:
    """C-3: the EMITTED state carries the structured goal, the plan's
    evaluation summary and the pipeline's decision summaries — the Phase B
    assets finally live in the Agent State."""
    states: list = []

    async def sink(state) -> None:
        states.append(state)

    loop = AgentLoop(decider=AskingDecider(), tools=_registry(_real_builder()))
    result = asyncio.run(
        run_agent(loop, AgentState(slots=_SLOTS), checkpoint_sink=sink)
    )
    assert result.stop_reason == "EMITTED"
    final = states[-1]
    assert "成都" in final.goal
    assert final.plan_evaluation is not None
    assert "status" in final.plan_evaluation
    assert final.decision_summaries, "the pipeline's decisions must be remembered"


def test_checkpoint_v2_round_trips_the_new_fields() -> None:
    from trip_agent.agent.state import (
        agent_state_from_dict,
        agent_state_to_dict,
        goal_from_slots,
    )

    state = AgentState(
        slots=_SLOTS,
        goal=goal_from_slots(_SLOTS),
        plan_evaluation={
            "status": "NEEDS_REPAIR",
            "failures": [
                {
                    "rule_id": "MUST_VISIT_COVERAGE",
                    "reason_code": "MUST_VISIT_PLACE_MISSING",
                    "message": "必去地点未被覆盖",
                }
            ],
        },
        decision_summaries=("预算紧张：已知票价超出上限的候选已降权",),
    )
    data = agent_state_to_dict(state)
    assert data["version"] == 2

    restored = agent_state_from_dict(data)
    assert restored.goal == state.goal
    assert restored.plan_evaluation == state.plan_evaluation
    assert restored.decision_summaries == state.decision_summaries


def test_checkpoint_v1_still_loads_with_defaults() -> None:
    """Backwards compatibility: a pre-C-3 checkpoint restores with the new
    fields empty (and the version stays v1 on the next write)."""
    from trip_agent.agent.state import agent_state_from_dict, agent_state_to_dict

    state = AgentState(slots=_SLOTS, goal="g", decision_summaries=("a",))
    data = agent_state_to_dict(state)
    data["version"] = 1
    for key in ("goal", "plan_evaluation", "decision_summaries"):
        data.pop(key)

    restored = agent_state_from_dict(data)
    assert restored.goal == ""
    assert restored.plan_evaluation is None
    assert restored.decision_summaries == ()
