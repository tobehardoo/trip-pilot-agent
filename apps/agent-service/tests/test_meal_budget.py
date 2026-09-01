"""V3 P2-1 — budget-aware meal planning (soft envelope, first-match-wins).

The audited gap: ``MealDemand.budget_per_person`` was a dead parameter and
the meal resolver took ``candidates[0]`` blind to cost.  Now the daily
budget feeds a per-meal SOFT envelope; the resolver prefers the first
restaurant within it and, when every candidate exceeds it, still serves the
first one with a BUDGET_CONSTRAINT trace — hunger is never an output.

Counterfactual discipline: the four scenarios below pin real selection
changes against the same recall batch (expensive restaurant FIRST, cheap
second), never "the field was read".
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from test_planning_intelligence_v1 import _single_day_payload

from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.planning.budget_policy import meal_budget_envelope
from trip_agent.planning.context_view import PlanningContextView
from trip_agent.planning.daily_schedule import MealDemand, plan_day
from trip_agent.planning.decision_trace import DecisionTrace
from trip_agent.providers.map import Coordinates, Poi, ProviderSuccess
from trip_agent.worker.contracts import PlanningContextFact, PlanningCreateCommand

_ENVELOPE = meal_budget_envelope(Decimal("250"), 2)  # budget 1500 / 2 pax / 3 days


def _spend_fact(name: str, amount: float) -> PlanningContextFact:
    statement = f"{name}人均 {amount:g} 元"
    return PlanningContextFact.model_validate(
        {
            "factId": f"fact_spend_{name}",
            "category": "REFERENCE_SPEND",
            "statement": statement,
            "normalizedValue": {"amount": amount, "currency": "CNY"},
            "evidence": statement,
            "effectiveDate": None,
            "checkedAt": "2026-09-08T00:00:00Z",
            "expiresAt": "2026-09-30T00:00:00Z",
            "stale": False,
            "sourceName": "大众点评",
            "sourceType": "OFFICIAL_TOURISM",
            "sourceUrl": "https://www.dianping.com",
            "reliabilityLevel": "OFFICIAL_TOURISM",
            "sourceReviewed": True,
            "hardConstraintEligible": False,
        }
    )


def _restaurant(provider_id: str, name: str) -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=120.15, latitude=30.25),
        type_name="餐饮",
        type_code="050000",
        province="浙江省",
        city="杭州市",
        district="西湖区",
        address=f"杭州市西湖区{name}",
    )


class _StaticMapProvider:
    def __init__(self, *pois: Poi) -> None:
        self._pois = pois

    async def search_pois(self, request: object) -> ProviderSuccess:
        del request
        return ProviderSuccess(
            data=self._pois,
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
            estimated=False,
        )


def _view(*spends: tuple[str, float], pressure: str = "TIGHT") -> PlanningContextView:
    return PlanningContextView(
        budget_per_person_per_day=Decimal("250"),
        budget_pressure=pressure,  # type: ignore[arg-type]
        activity_cost_ceiling=Decimal("87.50"),
        facts=tuple(_spend_fact(name, amount) for name, amount in spends),
        cost_hints={},
        days=(),
    )


def _resolve(
    restaurants: tuple[Poi, ...],
    *,
    spends: tuple[tuple[str, float], ...],
    envelope: Decimal | None = _ENVELOPE,
    pressure: str = "TIGHT",
) -> tuple[Poi | None, list[DecisionTrace]]:
    command = PlanningCreateCommand.model_validate(_single_day_payload("8 月 1 日晴。"))
    provider = AmapPlanningProvider(_StaticMapProvider(*restaurants), object())
    meal = MealDemand("LUNCH", 720, 780, region="西湖区", budget_per_person=envelope)
    traces: list[DecisionTrace] = []
    resolved = asyncio.run(
        provider._resolve_meal_poi(
            meal,
            command,
            decision_traces=traces,
            context_view=_view(*spends, pressure=pressure),
        )
    )
    return resolved, traces


# 贵餐厅 FIRST in the recall batch: pre-P2-1 the resolver took candidates[0]
# and always bound the expensive place.
_EXPENSIVE_FIRST = (_restaurant("r-expensive", "贵餐厅"), _restaurant("r-cheap", "小馆"))
_SPENDS = (("贵餐厅", 250.0), ("小馆", 30.0))


def test_tight_budget_switches_to_the_affordable_restaurant() -> None:
    """Scenario A — budget ¥1500 (envelope ¥37.50/person): the expensive
    first candidate is skipped, the affordable one is bound."""
    resolved, traces = _resolve(_EXPENSIVE_FIRST, spends=_SPENDS)

    assert resolved is not None and resolved.provider_id == "r-cheap"
    assert traces == []


def test_loose_budget_keeps_the_expensive_first_candidate() -> None:
    """Scenario B — budget ¥10000 (envelope ¥250/person): the expensive
    restaurant fits the envelope and regains its budget-side advantage."""
    loose_envelope = meal_budget_envelope(Decimal("10000") / 6, 2)
    resolved, traces = _resolve(
        _EXPENSIVE_FIRST, spends=_SPENDS, envelope=loose_envelope, pressure="RELAXED"
    )

    assert loose_envelope == Decimal("250.00")
    assert resolved is not None and resolved.provider_id == "r-expensive"
    assert traces == []


def test_only_affordable_restaurant_serves_every_budget() -> None:
    """Scenario C — only the cheap place exists: even the tightest budget
    binds it; never a placeholder."""
    resolved, traces = _resolve(
        (_restaurant("r-cheap", "小馆"),), spends=(("小馆", 30.0),)
    )

    assert resolved is not None and resolved.provider_id == "r-cheap"
    assert traces == []


def test_all_over_envelope_still_serves_and_traces() -> None:
    """Scenario D — every candidate exceeds the envelope: the first one is
    still bound (a meal always happens) and the overspend is traced."""
    resolved, traces = _resolve(
        (_restaurant("r-expensive", "贵餐厅"),), spends=(("贵餐厅", 250.0),)
    )

    assert resolved is not None and resolved.provider_id == "r-expensive"
    assert len(traces) == 1
    trace = traces[0]
    assert "BUDGET_CONSTRAINT" in trace.reason_codes
    evidence = {item.key: item.value for item in trace.evidence}
    assert evidence["meal_envelope_per_person"] == str(_ENVELOPE) == "37.50"
    assert evidence["restaurant_spend_per_person"] == "250.0"
    # Provenance discipline: the price source is stated, never disguised.
    assert evidence["spend_source"] == "PROVIDER"


def test_no_budget_stated_keeps_the_legacy_order() -> None:
    """Envelope None (no budget in the command) → the pre-P2-1 order applies
    (first candidate) with no trace."""
    resolved, traces = _resolve(_EXPENSIVE_FIRST, spends=_SPENDS, envelope=None)

    assert resolved is not None and resolved.provider_id == "r-expensive"
    assert traces == []


def test_estimated_prices_carry_their_rule_source_in_evidence() -> None:
    """A restaurant without a REFERENCE_SPEND fact prices at the documented
    default — and the trace says RULE_ESTIMATE, never PROVIDER."""
    resolved, traces = _resolve(
        (_restaurant("r-unknown", "无价餐厅"),), spends=()
    )

    assert resolved is not None and resolved.provider_id == "r-unknown"
    assert len(traces) == 1  # 50 > 37.50 → soft overspend traced
    evidence = {item.key: item.value for item in traces[0].evidence}
    assert evidence["restaurant_spend_per_person"] == "50.00"
    assert evidence["spend_source"] == "RULE_ESTIMATE"


def test_plan_day_attaches_the_per_meal_envelope() -> None:
    """The envelope rides on every MealDemand: bppd 250 split across the
    day's two meals → ¥37.50 each."""
    from datetime import date

    day = plan_day(
        trip_date=date(2026, 8, 1),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        arrival=None,
        departure=None,
        accommodation_known=False,
        candidates=(),
        pace="BALANCED",
        budget_per_person=Decimal("250"),
    )
    assert day.meal_demands, "a full day reserves meal time"
    assert all(
        demand.budget_per_person == Decimal("37.50") for demand in day.meal_demands
    )


def test_plan_day_without_budget_keeps_envelope_none() -> None:
    """No budget stated → the envelope stays None (absence never reads as
    pressure) and the demands are unchanged."""
    from datetime import date

    day = plan_day(
        trip_date=date(2026, 8, 1),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        arrival=None,
        departure=None,
        accommodation_known=False,
        candidates=(),
        pace="BALANCED",
    )
    assert all(demand.budget_per_person is None for demand in day.meal_demands)
