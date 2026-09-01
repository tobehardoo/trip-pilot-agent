"""Planning Intelligence V1 — context-aware mobility + data-truth cost model.

Counterfactual discipline: an input only counts as consumed when changing it
changes a decision.  These tests pin the V1 decision consumers:

1. weather statements → walking threshold → per-leg transport mode
2. TICKET_PRICE / REFERENCE_SPEND knowledge facts → activity cost +
   ``cost_source`` provenance (a 0 cost only ever comes from an explicit
   "free admission" fact, never from "unknown")
3. budget × weather × mobility → transport strategy (ordered conflict rules)
4. party size → per-person cost scaling
5. nights → accommodation cost
"""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

from test_planning_context_v2 import _poi, _route_success
from test_planning_context_v3 import _v3_command

from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.planning.budget_policy import (
    activity_cost_ceiling,
    budget_per_person_per_day,
    budget_pressure,
)
from trip_agent.planning.context_view import (
    budget_pressure_for,
    planning_context_weather_statements,
    resolve_transport_strategy_for_date,
    walking_threshold_seconds_for_date,
)
from trip_agent.planning.cost_model import (
    DEFAULT_ACCOMMODATION_PER_NIGHT,
    DEFAULT_MEAL_COST,
    FALLBACK_ATTRACTION_COST,
    resolve_attraction_cost,
    resolve_meal_cost,
    resolve_transit_cost,
)
from trip_agent.planning.transport_strategy import (
    DEFAULT_TRANSPORT_STRATEGY,
    resolve_transport_strategy,
)
from trip_agent.planning.trusted_context import planning_fact_impacts
from trip_agent.planning.weather_policy import (
    classify_weather_level,
    walking_threshold_for,
)
from trip_agent.providers.map import ProviderSuccess
from trip_agent.worker.contracts import (
    ItineraryActivity,
    PlanningContextFact,
    PlanningCreateCommand,
)

# -- weather policy -----------------------------------------------------------


def test_weather_level_classification_is_ordered_by_severity() -> None:
    assert classify_weather_level(()) is None
    assert classify_weather_level(("",)) is None
    assert classify_weather_level(("今天晴，26℃。",)) == "CLEAR"
    assert classify_weather_level(("多云转阴。",)) == "OVERCAST"
    assert classify_weather_level(("白天小雨。",)) == "DRIZZLE"
    assert classify_weather_level(("雷阵雨，31℃。",)) == "RAIN"
    assert classify_weather_level(("暴雨橙色预警。",)) == "STORM"
    # Severity wins over order: a storm term beats a clear term.
    assert classify_weather_level(("晴转暴雨。",)) == "STORM"


def test_walking_threshold_tightens_stepwise_and_keeps_product_default() -> None:
    assert walking_threshold_for(None) == 1200
    assert walking_threshold_for("CLEAR") == 1200
    assert walking_threshold_for("OVERCAST") == 1200
    assert walking_threshold_for("DRIZZLE") == 900
    assert walking_threshold_for("RAIN") == 600
    assert walking_threshold_for("STORM") == 300


def test_is_walkable_is_threshold_parameterized() -> None:
    from trip_agent.planning.transit_mode import is_walkable

    # Context-aware callers pass a tightened threshold.
    assert is_walkable(700, 900) is True
    assert is_walkable(700, 600) is False
    # Callers without a weather context keep the 20-minute product default.
    assert is_walkable(1200) is True
    assert is_walkable(1201) is False


def test_planning_context_weather_statements_apply_by_date() -> None:
    command = PlanningCreateCommand.model_validate(_weather_payload("8 月 1 日预计有雨"))
    context = command.payload.planning_context

    assert planning_context_weather_statements(context, date(2026, 8, 1)) != ()
    assert planning_context_weather_statements(context, date(2026, 8, 2)) == ()


def test_walking_threshold_for_date_resolves_from_command_facts() -> None:
    rain = PlanningCreateCommand.model_validate(_weather_payload("8 月 1 日雷阵雨"))

    assert walking_threshold_seconds_for_date(rain, date(2026, 8, 1)) == 600
    assert walking_threshold_seconds_for_date(rain, date(2026, 8, 2)) == 1200


# -- weather counterfactual (provider level) ----------------------------------


def _weather_payload(statement: str) -> dict:
    payload = _v3_command()
    payload["payload"]["trip"]["endDate"] = "2026-08-01"
    payload["payload"]["planningContext"]["travelEndDate"] = "2026-08-01"
    payload["payload"]["planningContext"]["stale"] = False
    payload["payload"]["planningContext"]["facts"] = [
        {
            "factId": "fact_weather_0123456789abcdef01234567",
            "category": "WEATHER",
            "statement": statement,
            "evidence": statement,
            "effectiveDate": "2026-08-01",
            "checkedAt": "2026-07-13T08:00:00Z",
            "expiresAt": "2026-08-03T08:00:00Z",
            "stale": False,
            "sourceName": "和风天气",
            "sourceType": "OFFICIAL_TOURISM",
            "sourceUrl": "https://www.qweather.com",
            "reliabilityLevel": "OFFICIAL_TOURISM",
            "sourceReviewed": True,
            "hardConstraintEligible": False,
        }
    ]
    payload["payload"]["trip"]["constraints"].update(
        {
            "arrival": None,
            "departure": None,
            "accommodation": None,
        }
    )
    return payload


def _single_day_payload(statement: str) -> dict:
    payload = _weather_payload(statement)
    payload["payload"]["trip"]["constraints"].update(
        {
            "arrival": None,
            "departure": None,
            "accommodation": None,
            "mustVisitPlaces": [],
            "avoidPlaces": [],
            "mealWindows": [
                {
                    "mealType": "LUNCH",
                    "startTime": "12:00",
                    "endTime": "13:00",
                    "source": "DISABLED",
                },
                {
                    "mealType": "DINNER",
                    "startTime": "18:00",
                    "endTime": "19:00",
                    "source": "DISABLED",
                },
            ],
            "mobilityLevel": "STANDARD",
            "preferences": [],
        }
    )
    return payload


def _single_day_standard_command(statement: str) -> PlanningCreateCommand:
    return PlanningCreateCommand.model_validate(_single_day_payload(statement))


def _budgeted_command(budget_amount: int) -> PlanningCreateCommand:
    payload = _single_day_payload("8 月 1 日晴天，26℃。")
    payload["payload"]["trip"]["constraints"]["budgetAmount"] = budget_amount
    return PlanningCreateCommand.model_validate(payload)


def _weather_route_provider(
    walking_duration: int,
    road_duration: int,
    transit_duration: int | None = None,
):
    class RouteProvider:
        async def get_route(self, request: object):
            if request.mode == "WALKING":
                return _route_success(request, distance=800, duration=walking_duration)
            if request.mode == "TRANSIT":
                return _route_success(
                    request, distance=3_000, duration=transit_duration or road_duration
                )
            return _route_success(request, distance=3_000, duration=road_duration)

    return RouteProvider()


def _planning_provider(
    *,
    walking_duration: int,
    road_duration: int,
    transit_duration: int | None = None,
):
    """Provider with TRANSIT available — without an explicit transit route
    provider the leg silently degrades to the DRIVING baseline."""
    route_provider = _weather_route_provider(
        walking_duration=walking_duration,
        road_duration=road_duration,
        transit_duration=transit_duration,
    )
    return AmapPlanningProvider(
        _weather_map_provider(), route_provider, route_provider
    )


def _weather_map_provider():
    candidates = (_poi("garden", "越秀公园"), _poi("museum", "广州博物馆"))

    class MapProvider:
        async def search_pois(self, request: object):
            return ProviderSuccess(
                data=candidates,
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 7, 14, tzinfo=UTC),
                estimated=False,
            )

    return MapProvider()


def test_weather_counterfactual_changes_the_transport_mode() -> None:
    """Same trip, only the weather statement differs: a leg that walks under
    a clear sky (1100s ≤ 1200s product rule) must NOT walk under rain
    (1100s > 600s tightened threshold) — the mode decision changed."""

    def planned_modes(statement: str) -> tuple[str, ...]:
        command = _single_day_standard_command(statement)
        result = asyncio.run(
            AmapPlanningProvider(
                _weather_map_provider(),
                _weather_route_provider(walking_duration=1_100, road_duration=600),
            ).plan(command)
        )
        legs = result.itinerary.days[0].transit_legs
        assert legs, "expected at least one routed leg between the two POIs"
        return tuple(leg.mode for leg in legs)

    clear_modes = planned_modes("8 月 1 日晴天，26℃。")
    rain_modes = planned_modes("8 月 1 日雷阵雨，31℃。")

    assert set(clear_modes) == {"WALKING"}
    assert "WALKING" not in set(rain_modes)


# -- cost model (data truth) --------------------------------------------------


def _ticket_fact(amount: float, target: str) -> dict:
    return {
        "factId": f"fact_ticket_{target}",
        "category": "TICKET_PRICE",
        "statement": f"{target}成人门票 {amount:g} 元",
        "normalizedValue": {"amount": amount, "currency": "CNY"},
        "evidence": f"{target}成人门票 {amount:g} 元",
        "effectiveDate": None,
        "checkedAt": "2026-07-13T08:00:00Z",
        "expiresAt": "2026-08-10T08:00:00Z",
        "stale": False,
        "sourceName": target,
        "sourceType": "OFFICIAL_ATTRACTION",
        "sourceUrl": "https://www.example.com/",
        "reliabilityLevel": "OFFICIAL_ATTRACTION",
        "sourceReviewed": True,
        "hardConstraintEligible": False,
    }


def test_attraction_cost_uses_official_ticket_price_and_zero_means_free() -> None:
    facts = (
        PlanningContextFact.model_validate(_ticket_fact(10.0, "陈家祠")),
        PlanningContextFact.model_validate(_ticket_fact(0.0, "越秀公园")),
    )

    priced = resolve_attraction_cost(facts, "陈家祠")
    free = resolve_attraction_cost(facts, "越秀公园")
    unknown = resolve_attraction_cost(facts, "白云山")

    assert priced.amount == Decimal("10.0") and priced.source == "PROVIDER"
    assert free.amount == Decimal("0") and free.source == "PROVIDER"
    assert unknown.amount == FALLBACK_ATTRACTION_COST
    assert unknown.source == "RULE_ESTIMATE"


def test_stale_or_unrelated_price_facts_are_ignored() -> None:
    stale = PlanningContextFact.model_validate({**_ticket_fact(999.0, "陈家祠"), "stale": True})
    facts = (stale,)

    resolved = resolve_attraction_cost(facts, "陈家祠")

    assert resolved.source == "RULE_ESTIMATE"


def test_meal_cost_uses_reference_spend_or_the_documented_default() -> None:
    spend_fact = PlanningContextFact.model_validate(
        {
            "factId": "fact_spend_陶陶居",
            "category": "REFERENCE_SPEND",
            "statement": "陶陶居人均 120 元",
            "normalizedValue": {"amount": 120.0, "currency": "CNY"},
            "evidence": "人均 120 元",
            "effectiveDate": None,
            "checkedAt": "2026-07-13T08:00:00Z",
            "expiresAt": "2026-08-10T08:00:00Z",
            "stale": False,
            "sourceName": "陶陶居",
            "sourceType": "OFFICIAL_ATTRACTION",
            "sourceUrl": "https://www.example.com/",
            "reliabilityLevel": "OFFICIAL_ATTRACTION",
            "sourceReviewed": True,
            "hardConstraintEligible": False,
        }
    )

    known = resolve_meal_cost((spend_fact,), "陶陶居")
    default = resolve_meal_cost((), "任 placename 餐厅")

    assert known.amount == Decimal("120.0") and known.source == "PROVIDER"
    assert default.amount == DEFAULT_MEAL_COST and default.source == "RULE_ESTIMATE"
    assert default.amount > 0, "an unknown meal must not silently read as free"


def test_provider_costs_carry_provenance_end_to_end() -> None:
    payload = _weather_payload("8 月 1 日晴天，26℃。")
    payload["payload"]["planningContext"]["facts"] = [
        _ticket_fact(10.0, "越秀公园"),
    ]
    payload["payload"]["trip"]["constraints"].update(
        {
            "arrival": None,
            "departure": None,
            "accommodation": None,
            "mustVisitPlaces": [],
            "avoidPlaces": [],
            "travelers": 2,
            "mealWindows": [
                {
                    "mealType": "LUNCH",
                    "startTime": "12:00",
                    "endTime": "13:00",
                    "source": "DISABLED",
                },
                {
                    "mealType": "DINNER",
                    "startTime": "18:00",
                    "endTime": "19:00",
                    "source": "DISABLED",
                },
            ],
            "mobilityLevel": "STANDARD",
            "preferences": [],
        }
    )
    command = PlanningCreateCommand.model_validate(payload)
    travelers = command.payload.trip.constraints.travelers

    result = asyncio.run(
        AmapPlanningProvider(
            _weather_map_provider(),
            _weather_route_provider(walking_duration=600, road_duration=900),
        ).plan(command)
    )

    attractions = {
        activity.provider_poi_id: activity
        for activity in result.itinerary.days[0].activities
        if activity.kind == "ATTRACTION"
    }
    priced = attractions["garden"]
    fallback = attractions["museum"]

    # P1-4: per-person prices scale with the party (2 travellers here).
    assert priced.estimated_cost == Decimal("10.0") * travelers
    assert priced.cost_source == "PROVIDER"
    assert fallback.estimated_cost == FALLBACK_ATTRACTION_COST * travelers
    assert fallback.cost_source == "RULE_ESTIMATE"
    assert result.itinerary.estimated_total_cost > 0


def test_cost_source_never_reaches_the_wire() -> None:
    activity = ItineraryActivity(
        title="越秀公园",
        start_time=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        end_time=datetime(2026, 8, 1, 11, 0, tzinfo=UTC),
        estimated_cost=Decimal("10.0"),
        cost_source="PROVIDER",
        source="DEMO",
    )

    assert activity.cost_source == "PROVIDER"
    assert "costSource" not in activity.model_dump(by_alias=True)
    assert "cost_source" not in activity.model_dump()


# -- honest fact impacts -------------------------------------------------------


def test_weather_impact_states_the_walking_policy_not_ranking() -> None:
    payload = _weather_payload("8 月 1 日预计有雨")
    command = PlanningCreateCommand.model_validate(payload)
    context = command.payload.planning_context
    assert context is not None

    impacts = planning_fact_impacts(context, ((date(2026, 8, 1), "越秀公园"),))

    assert len(impacts) == 1
    assert impacts[0].effect == "WEATHER_WALKING_POLICY_APPLIED"
    assert "提高优先级" not in impacts[0].reason
    assert "降低优先级" not in impacts[0].reason


def test_ticket_impact_only_claims_pricing_that_happened() -> None:
    payload = _weather_payload("8 月 1 日晴天。")
    payload["payload"]["planningContext"]["facts"] = [_ticket_fact(10.0, "陈家祠")]
    command = PlanningCreateCommand.model_validate(payload)
    context = command.payload.planning_context
    assert context is not None
    scheduled = ((date(2026, 8, 1), "陈家祠"),)

    applied = planning_fact_impacts(
        context, scheduled, provider_priced_targets=frozenset({"陈家祠"})
    )
    not_applied = planning_fact_impacts(context, scheduled)

    assert applied[0].effect == "OFFICIAL_TICKET_BUDGET_APPLIED"
    assert applied[0].reason == "官方门票价格已用于该活动成本估算"
    assert not_applied[0].effect == "TICKET_PRICE_EVIDENCE_AVAILABLE"
    assert not_applied[0].reason == "已获取官方门票价格证据，该活动成本暂未采用此价格"


# -- P1-3: budget pressure + transport conflict resolution ---------------------


def test_budget_pressure_is_derived_per_person_per_day() -> None:
    assert budget_per_person_per_day(None, 2, 3) is None
    assert budget_per_person_per_day(Decimal("0"), 2, 3) is None
    assert budget_per_person_per_day(Decimal("1500"), 2, 3) == Decimal("250")
    assert budget_pressure(Decimal("250")) == "TIGHT"
    assert budget_pressure(Decimal("500")) == "NORMAL"
    assert budget_pressure(Decimal("2500")) == "RELAXED"
    assert budget_pressure(None) is None
    assert activity_cost_ceiling(Decimal("250")) == Decimal("87.5")


def test_transport_strategy_resolves_context_conflicts_by_ordered_rules() -> None:
    # Reduced mobility in bad weather: safety first.
    assert resolve_transport_strategy(
        weather_level="RAIN", budget_pressure="NORMAL", mobility_reduced=True
    ).reason == "MOBILITY_SAFETY"
    # Storm beats everything.
    assert resolve_transport_strategy(
        weather_level="STORM", budget_pressure="RELAXED", mobility_reduced=False
    ).reason == "WEATHER_SAFETY"
    # Budget beats comfort: rain does NOT upgrade a tight budget to road.
    tight_rain = resolve_transport_strategy(
        weather_level="RAIN", budget_pressure="TIGHT", mobility_reduced=False
    )
    assert tight_rain.reason == "BUDGET_CONSTRAINT"
    assert tight_rain.max_transit_duration_ratio == 1.6
    # Comfort: a relaxed budget in bad weather may ride instead of bus.
    comfort_rain = resolve_transport_strategy(
        weather_level="RAIN", budget_pressure="RELAXED", mobility_reduced=False
    )
    assert comfort_rain.reason == "COMFORT_ALLOWS_ROAD"
    assert comfort_rain.max_transit_duration_ratio == 1.0
    # No context → baseline.
    default = resolve_transport_strategy(
        weather_level="CLEAR", budget_pressure="NORMAL", mobility_reduced=False
    )
    assert default == DEFAULT_TRANSPORT_STRATEGY
    # Weather still tightens walking even when the budget is relaxed.
    assert comfort_rain.walking_threshold_seconds < default.walking_threshold_seconds


def test_budget_counterfactual_changes_the_transport_mode() -> None:
    """Same trip, only the budget differs: with transit 1500s vs road 1000s
    (ratio 1.5) the baseline ratio 1.2 rejects TRANSIT, but a tight budget
    widens the tolerance to 1.6 and TRANSIT wins.  The mode changed."""

    def modes_for(budget_amount: int) -> tuple[str, ...]:
        command = _budgeted_command(budget_amount)
        provider = _planning_provider(
            walking_duration=3_000, road_duration=1_000, transit_duration=1_500
        )
        result = asyncio.run(provider.plan(command))
        legs = result.itinerary.days[0].transit_legs
        assert legs, "expected a routed leg between the two POIs"
        return tuple(leg.mode for leg in legs)

    tight = modes_for(500)  # 500 / (2 travellers × 1 day) = 250 → TIGHT
    relaxed = modes_for(5_000)  # 2500/day/person → RELAXED

    assert "TRANSIT" in tight, f"tight budget should accept transit, got {tight}"
    assert "TRANSIT" not in relaxed, (
        f"relaxed budget should keep the road baseline, got {relaxed}"
    )


def test_budget_pressure_reaches_the_resolved_strategy() -> None:
    tight = _budgeted_command(500)
    relaxed = _budgeted_command(5_000)

    assert budget_pressure_for(tight) == "TIGHT"
    assert budget_pressure_for(relaxed) == "RELAXED"
    assert (
        resolve_transport_strategy_for_date(tight, date(2026, 8, 1)).reason
        == "BUDGET_CONSTRAINT"
    )


# -- P1-4 / P1-5: party size and accommodation ---------------------------------


def test_travelers_counterfactual_scales_the_total_cost() -> None:
    def total_for(travelers: int) -> Decimal:
        payload = _single_day_payload("8 月 1 日晴天，26℃。")
        payload["payload"]["trip"]["constraints"]["travelers"] = travelers
        command = PlanningCreateCommand.model_validate(payload)
        result = asyncio.run(
            AmapPlanningProvider(
                _weather_map_provider(),
                _weather_route_provider(walking_duration=600, road_duration=900),
            ).plan(command)
        )
        return result.itinerary.estimated_total_cost

    assert total_for(4) > total_for(1) * 2


def test_transit_fare_scales_with_the_party_but_a_toll_does_not() -> None:
    # A TRANSIT ticket is per traveller.
    assert resolve_transit_cost(
        Decimal("6"), mode="TRANSIT", travelers=4
    ) == Decimal("24")
    # A DRIVING toll is per vehicle.
    assert resolve_transit_cost(
        Decimal("30"), mode="DRIVING", travelers=4
    ) == Decimal("30")
    assert resolve_transit_cost(None, mode="TRANSIT", travelers=4) is None


def test_accommodation_cost_counts_once_per_night() -> None:
    payload = _weather_payload("8 月 1 日晴天，26℃。")
    payload["payload"]["trip"]["endDate"] = "2026-08-03"
    payload["payload"]["planningContext"]["travelEndDate"] = "2026-08-03"
    payload["payload"]["trip"]["constraints"].update(
        {
            "arrival": None,
            "departure": None,
            "accommodation": None,
            "mustVisitPlaces": [],
            "avoidPlaces": [],
            "preferences": [],
        }
    )
    command = PlanningCreateCommand.model_validate(payload)

    result = asyncio.run(
        AmapPlanningProvider(
            _weather_map_provider(),
            _weather_route_provider(walking_duration=600, road_duration=900),
        ).plan(command)
    )

    lodging = [
        activity
        for day in result.itinerary.days
        for activity in day.activities
        if activity.kind == "ACCOMMODATION" and activity.estimated_cost > 0
    ]
    # 3 days → 2 nights; each night is charged once, per room (not per person).
    assert len(lodging) == 2
    assert all(
        activity.estimated_cost == DEFAULT_ACCOMMODATION_PER_NIGHT
        for activity in lodging
    )
    assert all(
        activity.cost_source == "CITY_ESTIMATE" for activity in lodging
    )
