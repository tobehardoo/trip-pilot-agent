"""B19-C — staged multi-mode recommendation tests (C1-C16).

Covers: WALKING short-circuit (C1), TRANSIT vs DRIVING ordered rules on real
provider facts (C2-C5), failure matrix (C6-C9), dynamic route-budget
reservation (C10), cache reuse (C11), route-fact same-source integrity (C12),
forward-fit with the selected transit duration (C13), and fixed-slot
feasibility with no feasibility override (C14), plus B18-B baseline
regressions (C15/C16).

Baseline-already-GREEN (locked, not broken): C1, C15, C16.
"""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from test_planning_worker import COMMAND

from trip_agent.domain.planning.protocols import PlanningInfeasibleError
from trip_agent.domain.shared import MAX_ROUTE_CALLS_PER_PLAN
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.planning.mode_recommendation import (
    MAX_TRANSFERS,
    MAX_TRANSIT_WALKING_METERS,
    ModeRecommendationReason,
    accessible_burdens,
    can_probe_transit,
    decide_transit_or_road,
)
from trip_agent.providers._route_contracts import RoutePlan, RouteStep
from trip_agent.providers.errors import PlanningProviderError
from trip_agent.providers.map import Coordinates, Poi, ProviderFailure, ProviderSuccess
from trip_agent.worker.contracts import PlanningCreateCommand


def _poi(
    pid: str,
    name: str,
    lon: float,
    lat: float,
    *,
    type_code: str = "110000",
    type_name: str = "风景名胜",
) -> Poi:
    return Poi(
        provider_id=pid,
        name=name,
        coordinates=Coordinates(longitude=lon, latitude=lat),
        type_name=type_name,
        type_code=type_code,
        province="广东省",
        city="广州市",
        district="越秀区",
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


class ScriptedModeProvider:
    """Mode-aware scripted route provider (WALKING / TRANSIT / DRIVING)."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.walking_plan: RoutePlan | None = None
        self.transit_plan: RoutePlan | None = None
        self.driving_plan: RoutePlan | None = None
        self.walk_failure: ProviderFailure | None = None
        self.transit_failure: ProviderFailure | None = None
        self.drive_failure: ProviderFailure | None = None

    async def get_route(self, request):
        self.calls.append(request.mode)
        if request.mode == "WALKING":
            if self.walk_failure is not None:
                return self.walk_failure
            plan = self.walking_plan
        elif request.mode == "TRANSIT":
            if self.transit_failure is not None:
                return self.transit_failure
            plan = self.transit_plan
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


def _plan(
    mode: str,
    duration_s: int,
    distance_m: int,
    *,
    walking_m: int | None = None,
    transfers: int | None = None,
    cost: float | None = None,
) -> RoutePlan:
    return RoutePlan(
        mode=mode,  # type: ignore[arg-type]
        distance_meters=distance_m,
        duration_seconds=duration_s,
        steps=(
            RouteStep(
                instruction="Step",
                distance_meters=distance_m,
                duration_seconds=duration_s,
                polyline=(
                    Coordinates(longitude=1, latitude=2),
                    Coordinates(longitude=3, latitude=4),
                ),
            ),
        ),
        polyline=(
            Coordinates(longitude=1, latitude=2),
            Coordinates(longitude=3, latitude=4),
        ),
        estimated_cost=cost,
        walking_distance_meters=walking_m,
        transfer_count=transfers,
    )


def _provider(scripted: ScriptedModeProvider) -> AmapPlanningProvider:
    return AmapPlanningProvider(scripted, scripted, transit_route=scripted)


def _departure() -> datetime:
    return datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def _pair(
    provider,
    origin,
    destination,
    *,
    city: str | None = None,
    calls_list: list[int] | None = None,
    cache: dict | None = None,
    remaining_legs: int = 1,
    mobility_reduced: bool = False,
):
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
            city=city,
            remaining_legs=remaining_legs,
            mobility_reduced=mobility_reduced,
        )
    )


# ── C1 — walking short-circuit wins even when road is faster ────────────────


def test_c1_walking_short_circuit_wins_over_faster_road() -> None:
    """walk 8min / road 4min -> WALKING (baseline GREEN, locked): walking is a
    product rule, not min(duration).  No TRANSIT/DRIVING comparison queries."""
    scripted = ScriptedModeProvider()
    scripted.walking_plan = _plan("WALKING", 480, 900)
    scripted.driving_plan = _plan("DRIVING", 240, 1800)
    scripted.transit_plan = _plan("TRANSIT", 900, 1500, walking_m=300, transfers=0)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.3260, 23.1360),  # ~700m -> within walking prefilter
        city="广州",
    )

    assert route.data.mode == "WALKING"
    assert route.data.duration_seconds == 480
    assert scripted.calls == ["WALKING"]


# ── C2 — TRANSIT clearly better ─────────────────────────────────────────────


def test_c2_transit_advantage_is_selected() -> None:
    """transit 21min / road 27min / 0 transfer / low walking -> TRANSIT."""
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 1260, 3400, walking_m=654, transfers=0, cost=2.0)
    scripted.driving_plan = _plan("DRIVING", 1620, 4200)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),  # ~8km -> no walking query
        city="广州",
    )

    assert route.data.mode == "TRANSIT"
    assert route.data.duration_seconds == 1260
    assert scripted.calls == ["TRANSIT", "DRIVING"]


# ── C3 — ROAD clearly better ────────────────────────────────────────────────


def test_c3_road_significantly_faster_is_selected() -> None:
    """transit 45min / 3 transfers / road 20min -> DRIVING."""
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 2700, 20000, walking_m=900, transfers=3)
    scripted.driving_plan = _plan("DRIVING", 1200, 18000)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),
        city="广州",
    )

    assert route.data.mode == "DRIVING"
    assert route.data.duration_seconds == 1200


# ── C4 — calibrated boundary: transit slightly slower but acceptable ─────────


def test_c4_transit_slightly_slower_within_ratio_is_selected() -> None:
    """transit 23min / road 20min / 0 transfer / low walking -> TRANSIT
    (ratio 1380/1200 = 1.15 <= 1.2), reason TRANSIT_COMPETITIVE_LOW_TRANSFER."""
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 1380, 6000, walking_m=200, transfers=0)
    scripted.driving_plan = _plan("DRIVING", 1200, 5800)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),
        city="广州",
    )

    assert route.data.mode == "TRANSIT"
    assert route.data.duration_seconds == 1380


def test_c4b_transit_ratio_exceeded_reverts_to_road() -> None:
    """transit 25min / road 20min (ratio 1.25 > 1.2) -> DRIVING even with
    zero transfers — locks the calibrated duration-ratio boundary."""
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 1500, 6000, walking_m=200, transfers=0)
    scripted.driving_plan = _plan("DRIVING", 1200, 5800)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),
        city="广州",
    )

    assert route.data.mode == "DRIVING"


# ── C5 — excessive transit walking burden ───────────────────────────────────


def test_c5_excessive_transit_walking_reverts_to_road() -> None:
    """transit 25min but 1800m walking (W=1500) -> DRIVING."""
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 1500, 6000, walking_m=1800, transfers=0)
    scripted.driving_plan = _plan("DRIVING", 1440, 5800)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),
        city="广州",
    )

    assert route.data.mode == "DRIVING"


# ── C6 — TRANSIT NO_RESULT ──────────────────────────────────────────────────


def test_c6_transit_no_result_falls_back_to_road() -> None:
    scripted = ScriptedModeProvider()
    scripted.transit_failure = _failure("ROUTE_NOT_FOUND")  # NO_RESULT
    scripted.driving_plan = _plan("DRIVING", 1620, 4200)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),
        city="广州",
    )

    assert route.data.mode == "DRIVING"
    assert scripted.calls == ["TRANSIT", "DRIVING"]


# ── C7 — TRANSIT recoverable failure ────────────────────────────────────────


@pytest.mark.parametrize("error_code", ["PROVIDER_RATE_LIMITED", "PROVIDER_TIMEOUT"])
def test_c7_transit_recoverable_failure_falls_back_to_road(error_code: str) -> None:
    scripted = ScriptedModeProvider()
    scripted.transit_failure = _failure(error_code)
    scripted.driving_plan = _plan("DRIVING", 1620, 4200)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),
        city="广州",
    )

    assert route.data.mode == "DRIVING"
    assert scripted.calls == ["TRANSIT", "DRIVING"]


# ── C8 — DRIVING recoverable failure -> TRANSIT ─────────────────────────────


def test_c8_driving_recoverable_failure_selects_transit() -> None:
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 1260, 3400, walking_m=654, transfers=0, cost=2.0)
    scripted.drive_failure = _failure("PROVIDER_UNAVAILABLE")
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),
        city="广州",
    )

    assert route.data.mode == "TRANSIT"
    assert route.data.duration_seconds == 1260
    assert scripted.calls == ["TRANSIT", "DRIVING"]


# ── C9 — WALKING recoverable failure -> recommendation continues ─────────────


def test_c9_walking_recoverable_failure_continues_to_recommendation() -> None:
    scripted = ScriptedModeProvider()
    scripted.walk_failure = _failure("PROVIDER_UNAVAILABLE")
    scripted.transit_plan = _plan("TRANSIT", 1260, 3400, walking_m=654, transfers=0)
    scripted.driving_plan = _plan("DRIVING", 1620, 4200)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.3260, 23.1360),  # ~700m -> walking queried first
        city="广州",
    )

    assert route.data.mode == "TRANSIT"
    assert scripted.calls == ["WALKING", "TRANSIT", "DRIVING"]


def test_c9b_non_recoverable_transit_failure_still_raises() -> None:
    """MALFORMED (PROVIDER_SCHEMA_CHANGED) is not an unavailability signal —
    it keeps raising even when DRIVING is available (D1 stays fail-closed)."""
    scripted = ScriptedModeProvider()
    scripted.transit_failure = _failure("PROVIDER_SCHEMA_CHANGED")
    scripted.driving_plan = _plan("DRIVING", 1620, 4200)
    provider = _provider(scripted)

    with pytest.raises(PlanningProviderError):
        _pair(
            provider,
            _poi("a", "A", 113.3200, 23.1300),
            _poi("b", "B", 113.4000, 23.1800),
            city="广州",
        )


def test_c9c_non_recoverable_driving_failure_still_raises() -> None:
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 1260, 3400, walking_m=654, transfers=0)
    scripted.drive_failure = _failure("PROVIDER_REQUEST_INVALID")  # INVALID_REQUEST
    provider = _provider(scripted)

    with pytest.raises(PlanningProviderError):
        _pair(
            provider,
            _poi("a", "A", 113.3200, 23.1300),
            _poi("b", "B", 113.4000, 23.1800),
            city="广州",
        )


# ── C10 — dynamic route budget reservation (no fixed 80 threshold) ───────────


def test_c10_budget_reserve_skips_transit_when_tight() -> None:
    """remaining budget == remaining legs -> transit probe not affordable;
    the leg degrades to DRIVING with BUDGET_DEGRADED (no fixed-80 magic)."""
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 1260, 3400, walking_m=654, transfers=0)
    scripted.driving_plan = _plan("DRIVING", 1620, 4200)
    provider = _provider(scripted)
    calls = [MAX_ROUTE_CALLS_PER_PLAN - 1]  # 95 used, 1 remaining, 1 leg left

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),
        city="广州",
        calls_list=calls,
        remaining_legs=1,
    )

    assert route.data.mode == "DRIVING"
    assert scripted.calls == ["DRIVING"]  # transit not probed
    assert calls == [MAX_ROUTE_CALLS_PER_PLAN]


def test_c10_budget_allows_transit_probe_when_reserve_holds() -> None:
    """2 remaining budget for the last leg -> transit probe + driving both fit."""
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 1260, 3400, walking_m=654, transfers=0)
    scripted.driving_plan = _plan("DRIVING", 1620, 4200)
    provider = _provider(scripted)
    calls = [MAX_ROUTE_CALLS_PER_PLAN - 2]  # 94 used, 2 remaining

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),
        city="广州",
        calls_list=calls,
        remaining_legs=1,
    )

    assert route.data.mode == "TRANSIT"
    assert scripted.calls == ["TRANSIT", "DRIVING"]


def test_c10_budget_reserves_for_many_remaining_legs() -> None:
    """6 remaining budget for 5 remaining legs -> probe allowed; for 10
    remaining legs -> probe skipped (baseline reserved for every leg)."""
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 1260, 3400, walking_m=654, transfers=0)
    scripted.driving_plan = _plan("DRIVING", 1620, 4200)
    provider = _provider(scripted)

    calls = [MAX_ROUTE_CALLS_PER_PLAN - 6]  # 90 used -> 6 remaining budget
    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),
        city="广州",
        calls_list=calls,
        remaining_legs=5,
    )
    assert scripted.calls == ["TRANSIT", "DRIVING"]
    assert route.data.mode == "TRANSIT"

    scripted2 = ScriptedModeProvider()
    scripted2.transit_plan = _plan("TRANSIT", 1260, 3400, walking_m=654, transfers=0)
    scripted2.driving_plan = _plan("DRIVING", 1620, 4200)
    provider2 = _provider(scripted2)
    calls2 = [MAX_ROUTE_CALLS_PER_PLAN - 6]
    route2 = _pair(
        provider2,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),
        city="广州",
        calls_list=calls2,
        remaining_legs=10,
    )
    assert scripted2.calls == ["DRIVING"]
    assert route2.data.mode == "DRIVING"


def test_c10_no_fixed_80_threshold() -> None:
    """At 79 used calls the old fixed-80 degrade would skip TRANSIT; the
    dynamic reserve (17 remaining budget for 1 leg) still allows the probe."""
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 1260, 3400, walking_m=654, transfers=0)
    scripted.driving_plan = _plan("DRIVING", 1620, 4200)
    provider = _provider(scripted)
    calls = [79]

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),
        city="广州",
        calls_list=calls,
        remaining_legs=1,
    )

    assert scripted.calls == ["TRANSIT", "DRIVING"]
    assert route.data.mode == "TRANSIT"


def test_c10_pure_budget_function_contract() -> None:
    assert can_probe_transit(remaining_budget=2, remaining_legs=1) is True
    assert can_probe_transit(remaining_budget=1, remaining_legs=1) is False
    assert can_probe_transit(remaining_budget=6, remaining_legs=5) is True
    assert can_probe_transit(remaining_budget=6, remaining_legs=6) is False
    assert can_probe_transit(remaining_budget=0, remaining_legs=1) is False


# ── C11 — cache reuse ────────────────────────────────────────────────────────


def test_c11_repeated_pair_reuses_cached_routes() -> None:
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 1260, 3400, walking_m=654, transfers=0)
    scripted.driving_plan = _plan("DRIVING", 1620, 4200)
    provider = _provider(scripted)
    cache: dict = {}
    calls = [0]

    origin = _poi("a", "A", 113.3200, 23.1300)
    destination = _poi("b", "B", 113.4000, 23.1800)
    _pair(provider, origin, destination, city="广州", cache=cache, calls_list=calls)
    _pair(provider, origin, destination, city="广州", cache=cache, calls_list=calls)

    assert scripted.calls == ["TRANSIT", "DRIVING"]  # no duplicate provider calls
    assert calls == [2]


# ── C12 — route facts are same-source ────────────────────────────────────────


def test_c12_selected_transit_facts_come_from_the_transit_plan() -> None:
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan(
        "TRANSIT", 1260, 3400, walking_m=654, transfers=0, cost=2.5
    )
    scripted.driving_plan = _plan("DRIVING", 1620, 4200, cost=8.0)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),
        city="广州",
    )

    assert route.data.mode == "TRANSIT"
    assert route.data.duration_seconds == 1260
    assert route.data.distance_meters == 3400
    assert route.data.estimated_cost == 2.5  # transit cost, not driving's 8.0
    assert route.data.polyline[0].longitude == 1


def test_c12_selected_driving_facts_come_from_the_driving_plan() -> None:
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 2700, 20000, walking_m=900, transfers=3)
    scripted.driving_plan = _plan("DRIVING", 1200, 18000, cost=5.0)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "A", 113.3200, 23.1300),
        _poi("b", "B", 113.4000, 23.1800),
        city="广州",
    )

    assert route.data.mode == "DRIVING"
    assert route.data.duration_seconds == 1200
    assert route.data.distance_meters == 18000
    assert route.data.estimated_cost == 5.0


# ── mobility accessibility burdens ───────────────────────────────────────────


def test_mobility_reduced_tightens_burdens() -> None:
    normal = accessible_burdens(
        mobility_reduced=False,
        max_transfers=MAX_TRANSFERS,
        max_transit_walking_meters=MAX_TRANSIT_WALKING_METERS,
    )
    reduced = accessible_burdens(
        mobility_reduced=True,
        max_transfers=MAX_TRANSFERS,
        max_transit_walking_meters=MAX_TRANSIT_WALKING_METERS,
    )
    assert normal == (MAX_TRANSFERS, MAX_TRANSIT_WALKING_METERS)
    assert reduced == (1, round(MAX_TRANSIT_WALKING_METERS * 0.5))


def test_mobility_reduced_rejects_a_transit_a_normal_user_would_accept() -> None:
    """transit 25min / 2 transfers / 900m walking vs road 22min: a normal user
    accepts TRANSIT (2 <= N=2, 900 <= W=1500); a REDUCED user rejects it
    (2 > N=1) — but never because of a blanket "prefer driving" rule."""
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 1500, 6000, walking_m=900, transfers=2)
    scripted.driving_plan = _plan("DRIVING", 1320, 5800)
    provider = _provider(scripted)
    origin = _poi("a", "A", 113.3200, 23.1300)
    destination = _poi("b", "B", 113.4000, 23.1800)

    normal = _pair(provider, origin, destination, city="广州")
    assert normal.data.mode == "TRANSIT"

    reduced = _pair(provider, origin, destination, city="广州", mobility_reduced=True)
    assert reduced.data.mode == "DRIVING"


# ── ordered-rule unit boundary (pure) ────────────────────────────────────────


def test_ordered_rules_boundaries() -> None:
    # ratio exceeded -> road
    ok, reason = decide_transit_or_road(
        1500, 1200, transfer_count=0, walking_distance_meters=100,
        max_transit_duration_ratio=1.2, max_transfers=2, max_transit_walking_meters=1500,
    )
    assert ok is False and reason is ModeRecommendationReason.ROAD_SIGNIFICANTLY_FASTER
    # transfers exceed -> road
    ok, reason = decide_transit_or_road(
        1380, 1200, transfer_count=3, walking_distance_meters=100,
        max_transit_duration_ratio=1.2, max_transfers=2, max_transit_walking_meters=1500,
    )
    assert ok is False and reason is ModeRecommendationReason.TRANSIT_TOO_MANY_TRANSFERS
    # walking exceeds -> road
    ok, reason = decide_transit_or_road(
        1380, 1200, transfer_count=0, walking_distance_meters=1800,
        max_transit_duration_ratio=1.2, max_transfers=2, max_transit_walking_meters=1500,
    )
    assert ok is False and reason is ModeRecommendationReason.TRANSIT_EXCESSIVE_WALKING
    # faster -> transit
    ok, reason = decide_transit_or_road(
        1200, 1500, transfer_count=0, walking_distance_meters=654,
        max_transit_duration_ratio=1.2, max_transfers=2, max_transit_walking_meters=1500,
    )
    assert ok is True and reason is ModeRecommendationReason.TRANSIT_FASTER_THAN_ROAD
    # competitive -> transit
    ok, reason = decide_transit_or_road(
        1380, 1200, transfer_count=1, walking_distance_meters=200,
        max_transit_duration_ratio=1.2, max_transfers=2, max_transit_walking_meters=1500,
    )
    assert ok is True and reason is ModeRecommendationReason.TRANSIT_COMPETITIVE_LOW_TRANSFER
    # missing transfer/walking facts are not grounds for rejection
    ok, _ = decide_transit_or_road(
        1380, 1200, transfer_count=None, walking_distance_meters=None,
        max_transit_duration_ratio=1.2, max_transfers=2, max_transit_walking_meters=1500,
    )
    assert ok is True


# ── full-plan: forward-fit / fixed-slot (C13/C14) ────────────────────────────


class StaticMapProvider:
    def __init__(self, pois: tuple[Poi, ...], *, meal_pois: tuple[Poi, ...] = ()) -> None:
        self._pois = pois
        self._meal_pois = meal_pois

    async def search_pois(self, request: object):
        keyword = request.keyword
        if keyword == "广州站":
            return self._success((_poi("anchor-station", "广州站", 113.26, 23.10),))
        if keyword == "广州南站":
            return self._success((_poi("anchor-south", "广州南站", 113.26, 22.99),))
        if keyword == "美食" or keyword.endswith(" 美食"):
            return self._success(self._meal_pois)
        return self._success(self._pois)

    @staticmethod
    def _success(pois: tuple[Poi, ...]) -> ProviderSuccess[tuple[Poi, ...]]:
        return ProviderSuccess(
            data=pois,
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 7, 23, tzinfo=UTC),
            estimated=False,
        )


class ModeAwareRouteProvider:
    """Real-plan route provider: TRANSIT 48min vs DRIVING 40min -> TRANSIT
    selected (48 <= 40*1.2); WALKING 10min for short legs."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_route(self, request):
        self.calls.append(request.mode)
        if request.mode == "WALKING":
            plan = _plan("WALKING", 600, 1200)
        elif request.mode == "TRANSIT":
            plan = _plan("TRANSIT", 2880, 9000, walking_m=300, transfers=0, cost=4.0)
        else:
            plan = _plan("DRIVING", 2400, 8000)
        return ProviderSuccess(
            data=plan,
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 8, 10, tzinfo=UTC),
            estimated=False,
        )


def _command(
    *,
    start: str = "2026-08-01",
    end: str = "2026-08-01",
    arrival: dict | None = None,
    departure: dict | None = None,
    accommodation: dict | None = None,
    must_visit: list[str] | None = None,
    preferences: list[str] | None = None,
    fixed_schedules: list[dict] | None = None,
) -> PlanningCreateCommand:
    payload = deepcopy(COMMAND)
    payload["schemaVersion"] = 2
    payload["payload"]["trip"]["startDate"] = start
    payload["payload"]["trip"]["endDate"] = end
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["schemaVersion"] = 2
    constraints["preferences"] = preferences or ["历史"]
    constraints["pace"] = "BALANCED"
    constraints["arrival"] = arrival
    constraints["departure"] = departure
    constraints["accommodation"] = accommodation
    constraints["mustVisitPlaces"] = must_visit or []
    constraints["avoidPlaces"] = []
    constraints["mealWindows"] = []
    constraints["mobilityLevel"] = "STANDARD"
    constraints["fixedSchedules"] = fixed_schedules or []
    return PlanningCreateCommand.model_validate(payload)


def test_c13_selected_transit_duration_enters_the_itinerary() -> None:
    """Two far-apart POIs (with resolved meals so legs exist): every non-walk
    leg must carry the real TRANSIT duration (2880s), not the DRIVING
    duration (2400s) — the fact that drives forward-fit comes from the
    selected route."""
    pois = (
        _poi("p1", "越秀公园", 113.30, 23.10),
        _poi("p2", "陈家祠", 113.36, 23.18),
    )
    # V2 semantics: meals only bind dining-class POIs, so the meal fixtures
    # carry the dining type instead of the scenic default.
    meals = (
        _poi("r1", "老字号粤菜馆", 113.33, 23.14, type_code="050000", type_name="餐饮服务"),
        _poi("r2", "云山茶楼", 113.34, 23.16, type_code="050000", type_name="餐饮服务"),
    )
    route_provider = ModeAwareRouteProvider()
    provider = AmapPlanningProvider(
        StaticMapProvider(pois, meal_pois=meals),
        route_provider,
        transit_route=route_provider,
    )

    result = asyncio.run(
        provider.plan(_command(must_visit=["越秀公园"], preferences=["历史"]))
    )

    legs = [leg for day in result.itinerary.days for leg in day.transit_legs]
    assert legs, "expected at least one transit leg"
    for leg in legs:
        if leg.mode == "TRANSIT":
            assert leg.duration_seconds == 2880, "transit leg must carry the transit duration"
            assert leg.provider == "AMAP"
            assert leg.estimated is False
    assert any(leg.mode == "TRANSIT" for leg in legs)
    # V2: the probe sequence changed when the candidates stopped including
    # the mislabeled restaurant POIs (pre-V2 they leaked into the attraction
    # pool as scenic POIs and produced a final walkable leg).  The honest
    # pool is p1/p2 only, so every leg probes TRANSIT then DRIVING.
    assert route_provider.calls == [
        "TRANSIT",
        "DRIVING",
        "TRANSIT",
        "DRIVING",
        "TRANSIT",
        "DRIVING",
    ]
    # F3: the itinerary total must include the real TRANSIT fare (¥4.00),
    # not only activity costs.
    transit_fare = sum(
        leg.estimated_cost or Decimal("0")
        for day in result.itinerary.days
        for leg in day.transit_legs
        if leg.mode == "TRANSIT"
    )
    assert transit_fare >= Decimal("4.00"), "fixture must carry the transit fare"
    assert (
        result.itinerary.estimated_total_cost >= transit_fare
    ), "estimated_total_cost must include the TRANSIT fare"


def test_c14_fixed_slot_infeasible_with_transit_raises_no_override() -> None:
    """A fixed departure the selected TRANSIT duration cannot fit raises
    PlanningInfeasibleError — the planner does NOT silently fall back to the
    faster DRIVING duration and does NOT retry with DRIVING (no feasibility
    override in v1, no mode oscillation: exactly one TRANSIT + one DRIVING
    probe)."""
    pois = (
        _poi("p1", "越秀公园", 113.30, 23.10),
        _poi("p2", "陈家祠", 113.36, 23.18),
    )
    route_provider = ModeAwareRouteProvider()
    provider = AmapPlanningProvider(
        StaticMapProvider(pois),
        route_provider,
        transit_route=route_provider,
    )

    with pytest.raises(PlanningInfeasibleError) as exc_info:
        asyncio.run(
            provider.plan(
                _command(
                    arrival={"placeName": "广州站", "time": "2026-08-01T09:00:00+08:00"},
                    departure={"placeName": "广州南站", "time": "2026-08-01T09:50:00+08:00"},
                )
            )
        )

    codes = {conflict.code for conflict in exc_info.value.conflicts}
    assert codes & {"FIXED_SCHEDULE_OVERLAP", "INSUFFICIENT_DAY_CAPACITY"}
    assert route_provider.calls == ["TRANSIT", "DRIVING"], (
        "transit was evaluated once and no feasibility-override retry happened"
    )


# ── C15/C16 — B18-B baseline regressions (already GREEN, locked) ─────────────


def test_c15_walking_golden_unchanged() -> None:
    scripted = ScriptedModeProvider()
    scripted.walking_plan = _plan("WALKING", 218, 623)
    scripted.driving_plan = _plan("DRIVING", 120, 1000)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "体育中心", 113.32, 23.13),
        _poi("b", "正佳广场", 113.326, 23.135),
    )

    assert route.data.mode == "WALKING"
    assert route.data.duration_seconds == 218
    assert scripted.calls == ["WALKING"]


def test_c16_long_road_golden_unchanged() -> None:
    """B18-B's long-distance behavior: walking is not even queried; the leg
    goes through the TRANSIT/DRIVING recommendation (B19-C semantics)."""
    scripted = ScriptedModeProvider()
    scripted.transit_plan = _plan("TRANSIT", 12139, 39000, walking_m=2981, transfers=4)
    scripted.driving_plan = _plan("DRIVING", 3682, 39000)
    provider = _provider(scripted)

    route = _pair(
        provider,
        _poi("a", "正佳", 113.32, 23.13),
        _poi("b", "白云机场", 113.30, 23.39),  # ~29km
        city="广州",
    )

    assert route.data.mode == "DRIVING"
    assert scripted.calls == ["TRANSIT", "DRIVING"]  # no WALKING query
    assert route.data.duration_seconds == 3682
