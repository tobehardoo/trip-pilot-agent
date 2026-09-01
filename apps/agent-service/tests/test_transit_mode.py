"""B18-B — walking/driving transport mode baseline tests.

RED scenarios (all fail on the pre-fix implementation):

- the planner hard-codes ``RouteRequest(mode="DRIVING")`` for every leg, so a
  1-metre leg is reported as "驾车" (audit evidence: 正佳广场 → 小林蓝鳄正佳广场
  1m/1s/DRIVING in ``business.transit_leg``);
- walking routes are never queried, so walkable short legs can never become
  WALKING;
- no haversine prefilter, no walking duration threshold, no walking→driving
  fallback on recoverable provider failure.
"""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.planning.transit_mode import (
    WALKING_PREFILTER_METERS,
    WALKING_THRESHOLD_SECONDS,
    is_walkable,
    should_try_walking,
    straight_line_distance_meters,
)
from trip_agent.providers._route_contracts import RoutePlan, RouteStep
from trip_agent.providers.errors import PlanningProviderError
from trip_agent.providers.map import Coordinates, Poi, ProviderFailure, ProviderSuccess
from trip_agent.worker.contracts import ActivityCoordinates

ZHENGJIA = (113.327019, 23.132145)  # 正佳广场 (real AMAP coordinates)
XIAOLIN = (113.327019, 23.132145)  # same-coordinate sibling (audit case)


def _poi(pid: str, name: str, lon: float, lat: float) -> Poi:
    return Poi(
        provider_id=pid,
        name=name,
        coordinates=Coordinates(longitude=lon, latitude=lat),
        type_name="风景名胜",
        type_code="110000",
        province="广东省",
        city="广州市",
        district="天河区",
        address=f"{name}地址",
    )


def _failure(error_code: str) -> ProviderFailure:
    return ProviderFailure(
        provider="AMAP",
        error_code=error_code,
        error_message="scripted failure",
        operation="ROUTE",
        retryable=True,
        latency_ms=1,
        fetched_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


class ScriptedRouteProvider:
    """Returns a RoutePlan whose mode mirrors the request mode, so a pre-fix
    planner (which always requests DRIVING) can never produce a WALKING leg."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.walking_plan: RoutePlan | None = None
        self.driving_plan: RoutePlan | None = None
        self.walk_failure: ProviderFailure | None = None
        self.drive_failure: ProviderFailure | None = None

    async def get_route(self, request):
        self.calls.append(request.mode)
        if request.mode == "WALKING":
            if self.walk_failure is not None:
                return self.walk_failure
            plan = self.walking_plan
        else:
            if self.drive_failure is not None:
                return self.drive_failure
            plan = self.driving_plan
        if plan is None:
            return _failure("ROUTE_NOT_FOUND")
        return ProviderSuccess(
            data=plan,
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 8, 10, tzinfo=UTC),
            estimated=False,
        )


def _plan(mode: str, distance_m: int, duration_s: int) -> RoutePlan:
    return RoutePlan(
        mode=mode,  # type: ignore[arg-type]
        distance_meters=distance_m,
        duration_seconds=duration_s,
        steps=(
            RouteStep(
                instruction="Walk" if mode == "WALKING" else "Drive",
                distance_meters=distance_m,
                duration_seconds=duration_s,
                polyline=(
                    Coordinates(longitude=1, latitude=2),
                    Coordinates(longitude=3, latitude=4),
                ),
            ),
        ),
        polyline=(Coordinates(longitude=1, latitude=2), Coordinates(longitude=3, latitude=4)),
    )


def _provider(scripted: ScriptedRouteProvider) -> AmapPlanningProvider:
    return AmapPlanningProvider(scripted, scripted)


def _departure() -> datetime:
    return datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def _pair(provider, origin, destination, *, calls_list=None, cache=None):
    if cache is None:
        cache = {}
    if calls_list is None:
        calls_list = [0]
    return asyncio.run(
        provider._route_for_pair(
            origin,
            destination,
            _departure(),
            cache,
            calls_list,
        )
    )


# ── pure mode decision helpers ───────────────────────────────────────────────


def test_straight_line_distance_is_pure_haversine() -> None:
    a = Coordinates(longitude=113.327019, latitude=23.132145)
    b = Coordinates(longitude=113.327019, latitude=23.132145)
    assert straight_line_distance_meters(a, b) == pytest.approx(0, abs=1)
    far = Coordinates(longitude=113.327019, latitude=23.132145 + 0.1)
    assert straight_line_distance_meters(a, far) > 10_000


def test_walking_threshold_constants() -> None:
    assert WALKING_THRESHOLD_SECONDS == 1200  # 20 minutes, product rule
    assert is_walkable(1200) is True
    assert is_walkable(1201) is False


def test_prefilter_is_a_cost_optimisation_boundary() -> None:
    assert should_try_walking(WALKING_PREFILTER_METERS) is True
    assert should_try_walking(WALKING_PREFILTER_METERS + 10) is False


# ── B1 — 1 metre / same-coordinate leg ───────────────────────────────────────


def test_b1_same_coordinate_leg_is_walking() -> None:
    scripted = ScriptedRouteProvider()
    scripted.walking_plan = _plan("WALKING", 1, 5)
    scripted.driving_plan = _plan("DRIVING", 1, 5)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "正佳广场", *ZHENGJIA),
        _poi("b", "小林蓝鳄正佳广场", *XIAOLIN),
    )

    assert route.data.mode == "WALKING"
    assert scripted.calls == ["WALKING"]  # no DRIVING query for a walkable leg


# ── B2 — ordinary walkable leg ───────────────────────────────────────────────


def test_b2_walkable_leg_uses_walking_facts() -> None:
    scripted = ScriptedRouteProvider()
    scripted.walking_plan = _plan("WALKING", 600, 600)
    scripted.driving_plan = _plan("DRIVING", 1800, 120)
    provider = _provider(scripted)

    route = _pair(provider, _poi("a", "A", 113.3200, 23.1300), _poi("b", "B", 113.3260, 23.1360))

    assert route.data.mode == "WALKING"
    assert route.data.duration_seconds == 600
    assert route.data.distance_meters == 600
    assert scripted.calls == ["WALKING"]


# ── B3 — walking > 20 minutes falls back to DRIVING ──────────────────────────


def test_b3_walking_over_threshold_queries_driving() -> None:
    scripted = ScriptedRouteProvider()
    scripted.walking_plan = _plan("WALKING", 2100, 1500)  # 25 min
    scripted.driving_plan = _plan("DRIVING", 2400, 480)
    provider = _provider(scripted)

    route = _pair(provider, _poi("a", "A", 113.3200, 23.1300), _poi("b", "B", 113.3260, 23.1360))

    assert route.data.mode == "DRIVING"
    assert scripted.calls == ["WALKING", "DRIVING"]
    # DRIVING facts come from the driving route, not the walking one.
    assert route.data.duration_seconds == 480
    assert route.data.distance_meters == 2400


# ── B4 — long distance never wastes a walking query ──────────────────────────


def test_b4_long_distance_only_queries_driving() -> None:
    scripted = ScriptedRouteProvider()
    scripted.walking_plan = _plan("WALKING", 5000, 3600)
    scripted.driving_plan = _plan("DRIVING", 35_000, 1800)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("hotel", "酒店", 113.32, 23.13),
        _poi("airport", "白云机场", 113.30, 23.39),  # ~29 km straight-line
    )

    assert route.data.mode == "DRIVING"
    assert scripted.calls == ["DRIVING"]


# ── B5 — recoverable walking failure falls back to DRIVING ───────────────────


def test_b5_walking_provider_failure_falls_back_to_driving() -> None:
    scripted = ScriptedRouteProvider()
    scripted.walk_failure = _failure("PROVIDER_UNAVAILABLE")
    scripted.driving_plan = _plan("DRIVING", 1400, 240)
    provider = _provider(scripted)

    route = _pair(provider, _poi("a", "A", 113.3200, 23.1300), _poi("b", "B", 113.3260, 23.1360))

    assert route.data.mode == "DRIVING"
    assert scripted.calls == ["WALKING", "DRIVING"]


# ── B6 — walking + driving both fail keeps the existing error policy ─────────


def test_b6_walking_and_driving_failures_raise() -> None:
    scripted = ScriptedRouteProvider()
    scripted.walk_failure = _failure("PROVIDER_UNAVAILABLE")
    scripted.drive_failure = _failure("PROVIDER_UNAVAILABLE")
    provider = _provider(scripted)

    with pytest.raises(PlanningProviderError):
        _pair(provider, _poi("a", "A", 113.3200, 23.1300), _poi("b", "B", 113.3260, 23.1360))


# ── B7 — route facts are consistent per mode ─────────────────────────────────


def test_b7_walking_route_facts_all_come_from_walking_route() -> None:
    scripted = ScriptedRouteProvider()
    walk_polyline = (
        Coordinates(longitude=113.3201, latitude=23.1301),
        Coordinates(longitude=113.3209, latitude=23.1309),
    )
    scripted.walking_plan = _plan("WALKING", 800, 700)
    scripted.walking_plan = scripted.walking_plan.model_copy(update={"polyline": walk_polyline})
    scripted.driving_plan = _plan("DRIVING", 900, 100)
    provider = _provider(scripted)

    route = _pair(provider, _poi("a", "A", 113.3200, 23.1300), _poi("b", "B", 113.3260, 23.1360))

    assert route.data.mode == "WALKING"
    assert route.data.polyline == walk_polyline
    assert route.data.distance_meters == 800
    assert route.data.duration_seconds == 700


def test_b7_driving_route_facts_all_come_from_driving_route() -> None:
    scripted = ScriptedRouteProvider()
    drive_polyline = (
        Coordinates(longitude=113.3101, latitude=23.2101),
        Coordinates(longitude=113.3109, latitude=23.2109),
    )
    scripted.walking_plan = _plan("WALKING", 2000, 1800)
    scripted.driving_plan = _plan("DRIVING", 2100, 600)
    scripted.driving_plan = scripted.driving_plan.model_copy(update={"polyline": drive_polyline})
    provider = _provider(scripted)

    route = _pair(provider, _poi("a", "A", 113.3200, 23.1300), _poi("b", "B", 113.3260, 23.1360))

    assert route.data.mode == "DRIVING"
    assert route.data.polyline == drive_polyline
    assert route.data.distance_meters == 2100
    assert route.data.duration_seconds == 600


# ── B8 — cost semantics ──────────────────────────────────────────────────────


def test_b8_walking_leg_cost_is_zero() -> None:
    scripted = ScriptedRouteProvider()
    scripted.walking_plan = _plan("WALKING", 600, 600)
    scripted.driving_plan = _plan("DRIVING", 1800, 120)
    provider = _provider(scripted)

    route = _pair(provider, _poi("a", "A", 113.3200, 23.1300), _poi("b", "B", 113.3260, 23.1360))
    leg = provider._leg_from_route(
        uuid4(),
        date(2026, 8, 20),
        0,
        1,
        route,
    )
    assert leg.mode == "WALKING"
    assert leg.estimated_cost == Decimal("0.00")
    assert leg.cost_source == "RULE_ESTIMATE"


def test_b8_driving_leg_keeps_its_cost_behavior() -> None:
    scripted = ScriptedRouteProvider()
    scripted.walking_plan = _plan("WALKING", 2000, 1800)
    scripted.driving_plan = _plan("DRIVING", 2100, 600)
    provider = _provider(scripted)

    route = _pair(provider, _poi("a", "A", 113.3200, 23.1300), _poi("b", "B", 113.3260, 23.1360))
    leg = provider._leg_from_route(uuid4(), date(2026, 8, 20), 0, 1, route)
    assert leg.mode == "DRIVING"


# ── B9 — persistence contract accepts WALKING ────────────────────────────────


def test_b9_transit_leg_contract_accepts_walking_mode() -> None:
    """The message contract / DTO already carry WALKING; a WALKING leg produced
    by the planner must be accepted as-is (never coerced back to DRIVING)."""
    from trip_agent.worker.contracts import TransitLeg

    leg = TransitLeg(
        from_activity_index=0,
        to_activity_index=1,
        mode="WALKING",
        distance_meters=600,
        duration_seconds=600,
        provider="AMAP",
        estimated=False,
        polyline=(ActivityCoordinates(longitude=Decimal("113.3201"), latitude=Decimal("23.1301")),),
        estimated_cost=Decimal("0.00"),
        cost_source="RULE_ESTIMATE",
    )
    assert leg.mode == "WALKING"
    assert leg.estimated_cost == Decimal("0.00")
