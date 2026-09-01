"""V2 P0-C — decision traces wire real decisions to the reason vocabulary.

Audit §16: V1 made weather and budget change real decisions, but no
``DecisionExplanation`` ever carried them — ``BUDGET_CONSTRAINT`` /
``TRANSIT_MODE`` had zero emitters across the repository.  These tests pin
the wiring end-to-end: strategy-stratified mode choices and tight-budget
demotion must surface as traces on ``PlanningResult`` and as evaluator
decisions with non-empty evidence.

Counterfactual discipline: the same trip under a clear sky must produce no
mode traces at all — the trace tracks the decision context, not the pipeline.
"""

import asyncio

from test_planning_context_v2 import _route_success  # noqa: F401  (re-exported via harness)
from test_planning_intelligence_v1 import (
    _budgeted_command,
    _single_day_standard_command,
    _weather_map_provider,
    _weather_route_provider,
)

from trip_agent.evaluation.evaluator import PlanEvaluator
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.worker.contracts import PlanningCreateCommand


def _planned(command: PlanningCreateCommand, *, walking_duration: int = 1_100):
    return asyncio.run(
        AmapPlanningProvider(
            _weather_map_provider(),
            _weather_route_provider(walking_duration=walking_duration, road_duration=600),
        ).plan(command)
    )


def _traces_with_code(result, code: str):
    return tuple(trace for trace in result.decision_traces if code in trace.reason_codes)


def _evidence(trace, key: str):
    return next(item for item in trace.evidence if item.key == key)


def test_rain_mode_decision_carries_transit_mode_trace() -> None:
    """Same trip, only the weather differs: under rain the 1100s walk exceeds
    the tightened 600s threshold, the mode comes from the ordered rules, and
    the decision must carry the weather evidence (audit AC-4)."""
    rain_result = _planned(_single_day_standard_command("8 月 1 日雷阵雨，31℃。"))

    traces = _traces_with_code(rain_result, "TRANSIT_MODE")
    assert traces, "a weather-stratified mode decision must be traced"
    mode_trace = traces[0]
    assert mode_trace.subject_type == "TRANSIT"
    # The 1100s walk exceeds the rain threshold; the ordered rules pick the
    # road mode (this fixture carries no transit advantage — V1's rain test
    # only pins "no WALKING").  The decision point is what gets traced.
    assert _evidence(mode_trace, "selected_mode").value in {"TRANSIT", "DRIVING"}
    assert _evidence(mode_trace, "weather_level").value == "RAIN"
    assert _evidence(mode_trace, "walking_threshold_seconds").value == "600"
    assert mode_trace.evidence  # non-empty by construction, pinned explicitly


def test_clear_sky_produces_no_mode_traces() -> None:
    """Counterfactual: the clear-sky run walks within the DEFAULT strategy —
    no context-stratified decision happened, so no mode trace may exist."""
    clear_result = _planned(_single_day_standard_command("8 月 1 日晴天，26℃。"))
    assert _traces_with_code(clear_result, "TRANSIT_MODE") == ()


def test_rain_walk_within_tightened_threshold_is_traced_as_walking() -> None:
    """A 500s walk still fits the rain threshold (600s): the plan walks, but
    the choice was made under a tightened threshold — the trace must say so."""
    rain_result = _planned(
        _single_day_standard_command("8 月 1 日雷阵雨，31℃。"),
        walking_duration=500,
    )

    traces = _traces_with_code(rain_result, "TRANSIT_MODE")
    assert traces, "a threshold-stratified walk decision must be traced"
    walk_trace = next(
        trace for trace in traces if _evidence(trace, "selected_mode").value == "WALKING"
    )
    assert _evidence(walk_trace, "weather_level").value == "RAIN"
    assert _evidence(walk_trace, "walking_threshold_seconds").value == "600"
    assert _evidence(walk_trace, "walking_duration_seconds").value == "500"


def test_tight_budget_demotion_carries_budget_constraint_trace() -> None:
    """P1-2 demoted ceiling-breaking candidates under a TIGHT budget; the
    decision is now recorded with its inputs (BUDGET_CONSTRAINT, plan level)."""
    result = _planned(_budgeted_command(500))  # 500 / 2 travelers / 1 day = 250 < 300

    traces = _traces_with_code(result, "BUDGET_CONSTRAINT")
    assert traces, "a tight-budget demotion must be traced"
    trace = traces[0]
    assert trace.subject_type == "PLAN"
    assert _evidence(trace, "budget_pressure").value == "TIGHT"
    assert any(item.key == "cost_ceiling" for item in trace.evidence)


def test_loose_budget_produces_no_budget_traces() -> None:
    """Counterfactual: a comfortable budget demotes nobody — no trace."""
    result = _planned(_budgeted_command(100_000))
    assert _traces_with_code(result, "BUDGET_CONSTRAINT") == ()


def test_evaluator_converts_traces_into_decision_explanations() -> None:
    """The full acceptance shape (audit AC-4): the evaluator output contains a
    TRANSIT decision with TRANSIT_MODE and weather evidence — the reason-code
    vocabulary is finally wired to a real decision."""
    command = _single_day_standard_command("8 月 1 日雷阵雨，31℃。")
    result = _planned(command)

    evaluation = PlanEvaluator().evaluate(command, result)

    decisions = tuple(
        decision
        for decision in evaluation.decisions
        if decision.reason_codes and "TRANSIT_MODE" in decision.reason_codes
    )
    assert decisions, "TRANSIT_MODE must reach the evaluator decisions"
    decision = decisions[0]
    assert decision.subject_type == "TRANSIT"
    assert any(item.key == "weather_level" for item in decision.evidence)
    assert any(item.key == "walking_threshold_seconds" for item in decision.evidence)


def test_relaxed_pace_policy_is_traced_as_a_schedule_decision() -> None:
    """Audit group G: a pace that changes the plan must carry observable
    evidence.  The RELAXED slot discount is a real policy decision, so the
    plan records it (PACE_POLICY); BALANCED stays trace-silent."""
    from test_planning_intelligence_v1 import _single_day_payload

    def command_with_pace(pace: str) -> PlanningCreateCommand:
        payload = _single_day_payload("8 月 1 日晴天，26℃。")
        payload["payload"]["trip"]["constraints"]["pace"] = pace
        return PlanningCreateCommand.model_validate(payload)

    relaxed_result = _planned(command_with_pace("RELAXED"))
    pace_traces = _traces_with_code(relaxed_result, "PACE_POLICY")
    assert pace_traces, "a RELAXED schedule policy must be traced"
    trace = pace_traces[0]
    assert trace.subject_type == "PLAN"
    assert _evidence(trace, "pace").value == "RELAXED"
    assert any(item.key == "slot_capacity_discount_minutes" for item in trace.evidence)

    balanced_result = _planned(command_with_pace("BALANCED"))
    assert _traces_with_code(balanced_result, "PACE_POLICY") == ()
