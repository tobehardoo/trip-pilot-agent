"""V3 P2-2c — a fixed appointment outranks budget comfort on its leg.

Conflict (audit §4, the one unadjudicated pair): a TIGHT budget widens the
transit tolerance to 1.6×, which can select a slower TRANSIT for the leg
into a fixed appointment — forward-fit then cannot fit the route before the
deadline and the whole plan fails.  The ordered-rules fix: legs INTO a
fixed slot resolve "arrival certainty > budget comfort" (ratio narrowed to
1.0, reason FIXED_SCHEDULE_DEADLINE); safety still outranks the deadline.

Counterfactual (single variable: the fixed appointment):
  without it — TIGHT tolerance selects TRANSIT (1300 ≤ 1000×1.6)
  with it    — the same leg must arrive on time → DRIVING (1300 > 1000×1.0)
"""

import asyncio
from datetime import UTC, datetime

from test_planning_intelligence_v1 import _single_day_payload

from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.planning.mode_recommendation import decide_transit_or_road
from trip_agent.planning.transport_strategy import (
    WIDENED_TRANSIT_DURATION_RATIO,
    TransportStrategy,
    deadline_strategy,
)
from trip_agent.providers.map import Coordinates, Poi, ProviderSuccess
from trip_agent.worker.contracts import PlanningCreateCommand

_WALKING = 3_000  # far too long to walk under any weather
_TRANSIT = 1_300  # 1.3× the road duration
_ROAD = 1_000
_FIXED_START = "2026-08-01T11:50:00+08:00"
_FIXED_END = "2026-08-01T12:50:00+08:00"


def _poi(provider_id: str, name: str, type_code: str) -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=113.26, latitude=23.13),
        type_name="风景名胜" if type_code == "110000" else "其他",
        type_code=type_code,
        province="广东省",
        city="广州市",
        district="越秀区",
        address=f"{name}地址",
    )


# 越秀公园 / 广州博物馆 are attraction candidates; 广州会议中心 is a
# non-attraction class (190000 → fail-closed out of the pool) that only the
# fixed schedule resolves.
POIS = (
    _poi("garden", "越秀公园", "110000"),
    _poi("museum", "广州博物馆", "140000"),
    _poi("venue", "广州会议中心", "190000"),
)


class _MapProvider:
    async def search_pois(self, request: object) -> ProviderSuccess:
        del request
        return ProviderSuccess(
            data=POIS,
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 7, 14, tzinfo=UTC),
            estimated=False,
        )


def _command(*, fixed: bool) -> PlanningCreateCommand:
    payload = _single_day_payload("8 月 1 日晴天，26℃。")
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["budgetAmount"] = 500  # 500 / 2 pax / 1 day = 250 → TIGHT
    if fixed:
        constraints["fixedSchedules"] = [
            {
                "placeName": "广州会议中心",
                "startTime": _FIXED_START,
                "endTime": _FIXED_END,
            }
        ]
    return PlanningCreateCommand.model_validate(payload)


class _RouteProvider:
    """Deterministic facts: walking hopeless, transit 1.3× road."""

    async def get_route(self, request):
        from trip_agent.providers._route_contracts import RoutePlan, RouteStep

        duration, distance, cost = {
            "WALKING": (_WALKING, 4_000, None),
            "TRANSIT": (_TRANSIT, 4_000, 4.0),
            "DRIVING": (_ROAD, 5_000, 28.0),
        }[request.mode]
        origin = Coordinates(longitude=113.26, latitude=23.13)
        destination = Coordinates(longitude=113.27, latitude=23.14)
        return ProviderSuccess(
            data=RoutePlan(
                mode=request.mode,
                distance_meters=distance,
                duration_seconds=duration,
                steps=(
                    RouteStep(
                        instruction=request.mode,
                        distance_meters=distance,
                        duration_seconds=duration,
                        polyline=(origin, destination),
                    ),
                ),
                polyline=(origin, destination),
                estimated_cost=cost,
                walking_distance_meters=200 if request.mode == "TRANSIT" else None,
                transfer_count=1 if request.mode == "TRANSIT" else None,
            ),
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 7, 14, tzinfo=UTC),
            estimated=False,
        )


def _planned(command: PlanningCreateCommand):
    route = _RouteProvider()
    return asyncio.run(
        AmapPlanningProvider(_MapProvider(), route, route).plan(command)
    )


def test_budget_tolerance_alone_would_pick_the_slower_transit() -> None:
    """The counterfactual baseline, pinned at the rule level: under a TIGHT
    budget the 1.3× transit IS acceptable (1300 ≤ 1000×1.6) — exactly the
    decision that missed the appointment pre-fix."""
    choose_transit, reason = decide_transit_or_road(
        _TRANSIT,
        _ROAD,
        transfer_count=1,
        walking_distance_meters=200,
        max_transit_duration_ratio=WIDENED_TRANSIT_DURATION_RATIO,
        max_transfers=2,
        max_transit_walking_meters=1_500,
    )
    assert choose_transit and reason.value == "TRANSIT_COMPETITIVE_LOW_TRANSFER"


def test_deadline_strategy_narrows_tolerance_but_yields_to_safety() -> None:
    tight = TransportStrategy(600, WIDENED_TRANSIT_DURATION_RATIO, "BUDGET_CONSTRAINT")
    deadline = deadline_strategy(tight)
    assert deadline.max_transit_duration_ratio == 1.0
    assert deadline.reason == "FIXED_SCHEDULE_DEADLINE"
    assert deadline.walking_threshold_seconds == 600

    # Safety outranks the deadline: the mobility/weather widening survives.
    stormy = TransportStrategy(300, WIDENED_TRANSIT_DURATION_RATIO, "WEATHER_SAFETY")
    assert deadline_strategy(stormy) is stormy


def test_fixed_appointment_leg_drives_and_arrives_on_time() -> None:
    """With the 11:50 appointment (gap 1200s), the tight-budget TRANSIT
    (1300s) would overflow the slot and fail the plan; the deadline rule
    drives (1000s) and the plan succeeds with the appointment covered."""
    result = _planned(_command(fixed=True))

    legs = [
        (leg.mode, leg.duration_seconds)
        for day in result.itinerary.days
        for leg in day.transit_legs
    ]
    assert ("DRIVING", _ROAD) in legs, f"expected a deadline DRIVING leg: {legs}"
    assert any(
        activity.title == "广州会议中心"
        for day in result.itinerary.days
        for activity in day.activities
    ), "the fixed appointment must be covered"

    traces = tuple(
        trace
        for trace in result.decision_traces
        if "FIXED_APPOINTMENT" in trace.reason_codes
    )
    assert traces, "the deadline decision must be explainable"
    evidence = {item.key: item.value for item in traces[0].evidence}
    assert evidence["strategy_reason"] == "FIXED_SCHEDULE_DEADLINE"
    assert evidence["selected_mode"] == "DRIVING"


def test_without_the_appointment_the_same_leg_is_transit() -> None:
    """Single-variable counterfactual: remove ONLY the fixed appointment —
    the tight-budget tolerance picks TRANSIT again and no deadline trace
    exists."""
    result = _planned(_command(fixed=False))

    modes = {leg.mode for day in result.itinerary.days for leg in day.transit_legs}
    assert "TRANSIT" in modes, modes
    assert not tuple(
        trace
        for trace in result.decision_traces
        if "FIXED_APPOINTMENT" in trace.reason_codes
    )
