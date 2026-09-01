"""V2 Planning Intelligence — POI semantic integrity invariants (SI-1..SI-8).

Audit basis: ``docs/architecture/planning-intelligence-v2-decision-loop-and-semantic-governance.md``
(§6 leakage table, §8 PlaceKind design, §17 invariants).  The classification
fixtures are the audited AMap ``type_code`` set; the pipeline test replays the
audited leak scenario end-to-end: a restaurant / hotel / mall recalled through
the default "美食" keyword must never surface as a sightseeing activity, and a
meal slot must only ever bind a dining-class POI.
"""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from test_planning_context_v2 import _route_success
from test_planning_intelligence_v1 import _single_day_payload

from trip_agent.domain.planning.protocols import PlanningInfeasibleError
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.planning.daily_schedule import MealDemand
from trip_agent.planning.poi_quality import (
    activity_candidate_eligible,
    classify_place,
    classify_poi_role,
    duration_profile_for,
)
from trip_agent.providers.map import Coordinates, Poi, ProviderSuccess
from trip_agent.worker.contracts import PlanningCreateCommand

# -- fixtures -----------------------------------------------------------------


def _poi(provider_id: str, name: str, type_code: str, district: str = "西湖区") -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=110.0, latitude=20.0),
        type_name="",
        type_code=type_code,
        province="广东省",
        city="广州市",
        district=district,
        address=f"{name}地址",
    )


def _command(**constraint_overrides: object) -> PlanningCreateCommand:
    payload = _single_day_payload("8 月 1 日晴天，26℃。")
    payload["payload"]["trip"]["constraints"].update(constraint_overrides)
    return PlanningCreateCommand.model_validate(payload)


class _StaticMapProvider:
    """Returns the same batch for every keyword search, ignoring the request."""

    def __init__(self, *pois: Poi) -> None:
        self._pois = pois

    async def search_pois(self, request: object) -> ProviderSuccess:
        del request
        return ProviderSuccess(
            data=self._pois,
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 7, 14, tzinfo=UTC),
            estimated=False,
        )


class _ConsistentRouteProvider:
    """AMAP-consistent route success (never triggers the metadata guard)."""

    async def get_route(self, request: object):
        return _route_success(request)


# -- §6.1 audit table: AMap type_code → PlaceKind ------------------------------

@pytest.mark.parametrize(
    ("type_code", "name", "expected_kind"),
    (
        # attractions (explicit rules)
        ("110000", "西湖", "ATTRACTION"),
        ("140000", "浙江省博物馆", "ATTRACTION"),
        ("080500", "长隆欢乐世界", "ATTRACTION"),
        # the audited leak classes — previously KEEP (fail-open)
        ("050000", "楼外楼", "RESTAURANT"),
        ("050300", "知味观", "RESTAURANT"),
        ("100000", "杭州君悦酒店", "ACCOMMODATION"),
        ("120000", "如家酒店", "OTHER"),
        ("060000", "杭州万象城", "SHOPPING"),
        ("060100", "天街商场", "SHOPPING"),
        # transport — the audited-correct behaviour must not regress
        ("150100", "萧山国际机场", "TRANSIT_HUB"),
        ("150200", "杭州东站", "TRANSIT_HUB"),
        ("150500", "龙翔桥地铁站", "TRANSIT_INFRA"),
        ("150700", "断桥公交站", "TRANSIT_INFRA"),
        ("150900", "西湖停车场", "TRANSIT_INFRA"),
        # fail-closed fallbacks
        ("", "无名地点", "UNKNOWN"),
        ("190000", "某政府机关", "OTHER"),
    ),
)
def test_classification_table_maps_amap_type_codes(
    type_code: str, name: str, expected_kind: str
) -> None:
    assert classify_place(_poi("poi-x", name, type_code)) == expected_kind


def test_name_fallback_covers_missing_codes_for_transport_only() -> None:
    # Missing type_code falls back to name markers for transport facilities…
    assert classify_place(_poi("poi-a", "杭州火车站", "")) == "TRANSIT_HUB"
    assert classify_place(_poi("poi-b", "龙翔桥地铁站", "")) == "TRANSIT_INFRA"
    # …and stays fail-closed for everything else (SI-6).
    assert classify_place(_poi("poi-c", "某乐园", "")) == "UNKNOWN"
    assert classify_place(_poi("poi-d", "某酒店", "")) == "UNKNOWN"


def test_poi_role_derivation_preserves_transport_and_rejects_leaks() -> None:
    # SI-4: the audited-correct transport behaviour is regression-protected.
    assert classify_poi_role(_poi("hub", "杭州东站", "150200")) == "ANCHOR_ONLY"
    assert not activity_candidate_eligible(_poi("hub", "杭州东站", "150200"))
    assert classify_poi_role(_poi("metro", "龙翔桥地铁站", "150500")) == "FILTER"
    assert classify_poi_role(_poi("scenic", "西湖", "110000")) == "KEEP"
    assert activity_candidate_eligible(_poi("scenic", "西湖", "110000"))
    # SI-1/2/3: dining, accommodation and shopping never become attractions.
    for type_code in ("050000", "100000", "120000", "060000"):
        poi = _poi("poi-leak", "泄漏候选", type_code)
        assert classify_poi_role(poi) == "FILTER", type_code
        assert not activity_candidate_eligible(poi), type_code
    # SI-6: unknown / other classes are fail-closed out of the pool.
    assert classify_poi_role(_poi("poi-u", "无名地点", "")) == "FILTER"
    assert not activity_candidate_eligible(_poi("poi-u", "无名地点", ""))


def test_dining_and_accommodation_never_take_attraction_duration_profiles() -> None:
    # SI-7: a restaurant previously received the 180-minute NORMAL profile.
    dining = duration_profile_for(_poi("poi-r", "楼外楼", "050000"))
    assert dining.source_ref == "category:dining"
    assert dining.max_minutes <= 90
    assert dining.max_minutes < 180
    accommodation = duration_profile_for(_poi("poi-h", "杭州君悦酒店", "100000"))
    assert accommodation.source_ref == "category:accommodation"
    assert accommodation.max_minutes < 180
    # Semantic kind wins over name markers: a restaurant named after a
    # full-day marker ("乐园") is still a dining stop.
    masked = duration_profile_for(_poi("poi-r2", "楼外楼美食乐园", "050000"))
    assert masked.source_ref == "category:dining"
    # Pinned records carry no type_code: the marker/system fallback is the
    # documented boundary of the kind-first dispatch, unchanged from V1.
    pinned_unknown = duration_profile_for(_poi("poi-p", "某乐园", ""))
    assert pinned_unknown.source_ref == "category:full-day"


def test_meal_resolver_requires_restaurant_semantics() -> None:
    command = _command()
    provider = AmapPlanningProvider(
        _StaticMapProvider(
            _poi("poi-scenic", "西湖", "110000"),
            _poi("poi-mall", "杭州万象城", "060000"),
            _poi("poi-restaurant", "楼外楼", "050000"),
        ),
        _ConsistentRouteProvider(),
    )
    meal = MealDemand("LUNCH", 720, 780)

    # SI-5: only the dining-class POI can serve the meal.
    resolved = asyncio.run(provider._resolve_meal_poi(meal, command))
    assert resolved is not None and resolved.provider_id == "poi-restaurant"

    # Region preference still applies among restaurant-class candidates only.
    regional_provider = AmapPlanningProvider(
        _StaticMapProvider(
            _poi("poi-restaurant", "楼外楼", "050000", district="西湖区"),
            _poi("poi-other", "知味观", "050000", district="上城区"),
            _poi("poi-mall", "杭州万象城", "060000", district="西湖区"),
        ),
        _ConsistentRouteProvider(),
    )
    regional = asyncio.run(
        regional_provider._resolve_meal_poi(MealDemand("LUNCH", 720, 780, region="西湖区"), command)
    )
    assert regional is not None and regional.provider_id == "poi-restaurant"

    # No dining-class POI in the batch → None (the caller keeps the
    # placeholder meal; behaviour unchanged from the audit baseline).
    empty_provider = AmapPlanningProvider(
        _StaticMapProvider(
            _poi("poi-scenic", "西湖", "110000"),
            _poi("poi-mall", "杭州万象城", "060000"),
        ),
        _ConsistentRouteProvider(),
    )
    assert asyncio.run(empty_provider._resolve_meal_poi(meal, command)) is None

    # Already-used restaurants are not reused for the next meal.
    excluded = asyncio.run(
        provider._resolve_meal_poi(
            MealDemand("DINNER", 1080, 1140),
            command,
            excluded_provider_ids=frozenset({"poi-restaurant"}),
        )
    )
    assert excluded is None


def _anchor_command(**anchor_fields: object) -> PlanningCreateCommand:
    return _command(**{"accommodation": None, **anchor_fields})


def test_accommodation_anchor_requires_accommodation_semantics() -> None:
    # SI-8: a same-name scenic POI must not become the accommodation anchor.
    scenic_provider = AmapPlanningProvider(
        _StaticMapProvider(_poi("poi-scam", "君悦酒店", "110000")),
        _ConsistentRouteProvider(),
    )
    command = _anchor_command(accommodation={"placeName": "君悦酒店"})
    with pytest.raises(PlanningInfeasibleError):
        asyncio.run(scenic_provider._resolve_travel_anchors(command))

    # A dining-class impostor fails closed the same way.
    dining_provider = AmapPlanningProvider(
        _StaticMapProvider(_poi("poi-fake", "君悦酒店", "050000")),
        _ConsistentRouteProvider(),
    )
    with pytest.raises(PlanningInfeasibleError):
        asyncio.run(dining_provider._resolve_travel_anchors(command))

    # Accommodation-class (and code-less UNKNOWN) records resolve.
    hotel_provider = AmapPlanningProvider(
        _StaticMapProvider(_poi("poi-hotel", "君悦酒店", "100000")),
        _ConsistentRouteProvider(),
    )
    resolved = asyncio.run(hotel_provider._resolve_travel_anchors(command))
    assert resolved.accommodation is not None
    assert resolved.accommodation.provider_id == "poi-hotel"

    unknown_provider = AmapPlanningProvider(
        _StaticMapProvider(_poi("poi-legacy", "君悦酒店", "")),
        _ConsistentRouteProvider(),
    )
    resolved = asyncio.run(unknown_provider._resolve_travel_anchors(command))
    assert resolved.accommodation is not None
    assert resolved.accommodation.provider_id == "poi-legacy"


def test_arrival_anchor_keeps_transport_hub_semantics() -> None:
    # Only the accommodation anchor is semantically gated; arrival/departure
    # anchors are legitimately transport hubs and stay resolvable.
    provider = AmapPlanningProvider(
        _StaticMapProvider(_poi("poi-station", "杭州东站", "150200")),
        _ConsistentRouteProvider(),
    )
    command = _anchor_command(
        arrival={
            "placeName": "杭州东站",
            "time": "2026-08-01T11:00:00+08:00",
        }
    )
    resolved = asyncio.run(provider._resolve_travel_anchors(command))
    assert resolved.arrival is not None
    assert resolved.arrival.provider_id == "poi-station"


def test_pipeline_never_emits_leaked_pois_as_sightseeing() -> None:
    """End-to-end replay of the audited leak: the default "美食" recall
    keyword pulls a restaurant into the raw batch, yet the emitted plan must
    contain it only as a MEAL binding — never as ATTRACTION/EXPERIENCE, and
    the hotel/mall must disappear entirely (SI-1/2/3 + SI-5)."""
    payload = _single_day_payload("8 月 1 日晴天，26℃。")
    windows = payload["payload"]["trip"]["constraints"]["mealWindows"]
    for window in windows:
        if window["mealType"] == "LUNCH":
            window["source"] = "DEFAULT"
    command = PlanningCreateCommand.model_validate(payload)
    provider = AmapPlanningProvider(
        _StaticMapProvider(
            _poi("poi-lake", "西湖", "110000"),
            _poi("poi-museum", "浙江省博物馆", "140000"),
            _poi("poi-restaurant", "楼外楼", "050000"),
            _poi("poi-hotel", "杭州君悦酒店", "100000"),
            _poi("poi-mall", "杭州万象城", "060000"),
        ),
        _ConsistentRouteProvider(),
    )

    result = asyncio.run(deepcopy(provider).plan(command))
    days = result.itinerary.days
    assert days, "expected a planned day"

    sightseeing_ids = tuple(
        activity.provider_poi_id
        for day in days
        for activity in day.activities
        if activity.kind in {"ATTRACTION", "EXPERIENCE"}
    )
    assert set(sightseeing_ids) == {"poi-lake", "poi-museum"}, sightseeing_ids

    meal_bindings = tuple(
        activity.provider_poi_id
        for day in days
        for activity in day.activities
        if activity.kind == "MEAL" and activity.provider_poi_id is not None
    )
    assert meal_bindings == ("poi-restaurant",)

    leaked_ids = {"poi-hotel", "poi-mall"}
    assert not (leaked_ids & set(sightseeing_ids)), "hotel/mall leaked into the plan"


def test_pool_admission_surfaces_as_provider_constraint_trace() -> None:
    """V3 P2-2b: fail-closed pool admission is a real decision — the plan
    records how many non-attraction candidates stayed out of the pool."""
    # The command's destination is 广州 — POIs must match its city to pass
    # the ranker's own hard filter (that gate is NOT the one under test).
    def _gz_poi(provider_id: str, name: str, type_code: str) -> Poi:
        base = _poi(provider_id, name, type_code)
        return base.model_copy(update={"city": "广州市", "province": "广东省"})

    command = PlanningCreateCommand.model_validate(
        deepcopy(_single_day_payload("8 月 1 日晴天，26℃。"))
    )
    provider = AmapPlanningProvider(
        _StaticMapProvider(
            _gz_poi("poi-lake", "越秀公园", "110000"),
            _gz_poi("poi-restaurant", "广州酒家", "050000"),
            _gz_poi("poi-hotel", "广州花园酒店", "100000"),
            _gz_poi("poi-mall", "天河城", "060000"),
        ),
        _ConsistentRouteProvider(),
    )

    result = asyncio.run(deepcopy(provider).plan(command))

    traces = tuple(
        trace for trace in result.decision_traces if "PROVIDER_CONSTRAINT" in trace.reason_codes
    )
    assert traces, "pool admission must be explainable"
    evidence = {item.key: item.value for item in traces[0].evidence}
    assert evidence["excluded_count"] == "3"
    assert "广州花园酒店" in evidence["excluded_names"]

    # Counterfactual: an attraction-only batch admits everything → no trace.
    clean = asyncio.run(
        deepcopy(
            AmapPlanningProvider(
                _StaticMapProvider(_gz_poi("poi-lake", "越秀公园", "110000")),
                _ConsistentRouteProvider(),
            )
        ).plan(command)
    )
    assert not tuple(
        trace for trace in clean.decision_traces if "PROVIDER_CONSTRAINT" in trace.reason_codes
    )
