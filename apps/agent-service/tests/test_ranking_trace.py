"""V3 P2-2a — ranking reasons surface as decision traces.

The ranker already computes per-candidate reasons (PREFERENCE_MATCH,
MUST_VISIT_MATCH, GUIDE_FACT_MATCH, BUDGET_TIGHT_COST_PENALTY); these were
invisible outside the ranking object.  P2-2a only TRANSPORTS them into
plan-level DecisionTraces — the scoring itself is untouched, and the
counterfactual discipline holds: no signal → no trace.
"""

import asyncio
from copy import deepcopy

from test_planning_intelligence_v1 import (
    _single_day_payload,
    _weather_map_provider,
    _weather_route_provider,
)

from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.worker.contracts import PlanningCreateCommand


def _command(
    *,
    preferences: tuple[str, ...] = (),
    must_visit: tuple[str, ...] = (),
    budget: int | None = None,
    guide_statement: str | None = None,
) -> PlanningCreateCommand:
    payload = _single_day_payload("8 月 1 日晴天，26℃。")
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["preferences"] = list(preferences)
    constraints["mustVisitPlaces"] = list(must_visit)
    if budget is not None:
        constraints["budgetAmount"] = budget
    if guide_statement is not None:
        payload["payload"]["guideEvidence"]["facts"] = [
            {
                "guideImportId": "11111111-1111-1111-1111-111111111111",
                "factId": "22222222-2222-2222-2222-222222222222",
                "category": "TIP",
                "statement": guide_statement,
                "evidence": guide_statement,
                "sourceType": "PUBLIC_GUIDE_URL",
                "sourceUrl": "https://www.gz.gov.cn/guide",
                "sourceHost": "www.gz.gov.cn",
                "sourceTitle": "广州一日游攻略",
                "confidence": 0.9,
                "effectiveDate": "2026-08-01",
                "observedAt": "2026-07-10T00:00:00Z",
                "expiresAt": "2026-08-31T00:00:00Z",
            }
        ]
    return PlanningCreateCommand.model_validate(payload)


def _planned(command: PlanningCreateCommand):
    route = _weather_route_provider(walking_duration=800, road_duration=600)
    return asyncio.run(
        AmapPlanningProvider(_weather_map_provider(), route, route).plan(command)
    )


def _traces_with(result, code: str):
    return tuple(t for t in result.decision_traces if code in t.reason_codes)


def _evidence(trace, key: str):
    return next(item for item in trace.evidence if item.key == key)


def test_preference_match_surfaces_as_interest_trace() -> None:
    result = _planned(_command(preferences=("公园",)))

    traces = _traces_with(result, "INTEREST_MATCH")
    assert traces, "a matched preference must be explainable"
    assert "越秀公园" in _evidence(traces[0], "preference_matched").value


def test_no_preference_produces_no_interest_trace() -> None:
    """Counterfactual: strip the preference → the signal disappears."""
    result = _planned(_command(preferences=()))
    assert _traces_with(result, "INTEREST_MATCH") == ()


def test_guide_recommendation_surfaces_as_interest_trace() -> None:
    result = _planned(
        _command(guide_statement="越秀公园值得去，人少且适合散步。")
    )

    traces = _traces_with(result, "INTEREST_MATCH")
    assert traces, "a guide recommendation hit must be explainable"
    assert "越秀公园" in _evidence(traces[0], "guide_matched").value


def test_must_visit_surfaces_as_must_visit_trace() -> None:
    result = _planned(_command(must_visit=("越秀公园",)))

    traces = _traces_with(result, "MUST_VISIT")
    assert traces, "a pinned must-visit must be explainable"
    assert "越秀公园" in _evidence(traces[0], "must_visit_matched").value

    without = _planned(_command(must_visit=()))
    assert _traces_with(without, "MUST_VISIT") == ()


def test_budget_penalty_evidence_names_the_penalized_candidates() -> None:
    """The existing TIGHT-budget trace now names who actually lost ground:
    越秀公园 priced at ¥500/person against a ¥87.50 ceiling."""
    payload = deepcopy(_single_day_payload("8 月 1 日晴天，26℃。"))
    payload["payload"]["trip"]["constraints"]["budgetAmount"] = 500
    payload["payload"]["planningContext"]["facts"].append(
        {
            "factId": "fact_ticket_yuexiu",
            "category": "TICKET_PRICE",
            "statement": "越秀公园成人门票 500 元",
            "normalizedValue": {"amount": 500, "currency": "CNY"},
            "evidence": "越秀公园成人门票 500 元",
            "effectiveDate": None,
            "checkedAt": "2026-07-30T00:00:00Z",
            "expiresAt": "2026-08-31T00:00:00Z",
            "stale": False,
            "sourceName": "广州文旅",
            "sourceType": "OFFICIAL_TOURISM",
            "sourceUrl": "https://www.gz.gov.cn",
            "reliabilityLevel": "OFFICIAL_TOURISM",
            "sourceReviewed": True,
            "hardConstraintEligible": False,
        }
    )
    result = _planned(PlanningCreateCommand.model_validate(payload))

    traces = _traces_with(result, "BUDGET_CONSTRAINT")
    assert traces, "a tight-budget demotion must be traced"
    penalized = _evidence(traces[0], "penalized_candidates").value
    assert "越秀公园" in penalized, penalized
