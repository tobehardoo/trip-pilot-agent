"""B13_FIX R5 (P1-2) — structured place refs must resolve by exact provider
POI identity on the Python planner side.

RED scenarios:
- a structured arrival anchor pins the exact providerPoiId even when the
  recalled POI title differs from the display name;
- a structured anchor whose id is NOT recalled fails closed with
  TRAVEL_ANCHOR_UNAVAILABLE — never a same-name fallback;
- a structured must-visit whose id is NOT recalled is pinned from the
  server-signed ref (B13_FIX.2 R9) — the exact providerPoiId is placed, and
  a same-name POI is never treated as the must-visit place;
- a structured must-visit whose id IS recalled binds even when its recalled
  title carries a facility suffix;
- legacy text anchors keep name-based resolution (unchanged).
"""

import asyncio
from datetime import UTC, datetime

import pytest

from trip_agent.domain.planning.protocols import (
    PlanningInfeasibleError,
)
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.providers.map import Coordinates, Poi, ProviderSuccess
from trip_agent.providers.route import RoutePlan, RouteStep

AMAP_REF = {
    "provider": "AMAP",
    "providerPoiId": "B001234567",
    "name": "陈家祠",
    "address": "广州市荔湾区中山七路恩龙里34号",
    "province": "广东省",
    "city": "广州市",
    "district": "荔湾区",
    "longitude": 113.2405,
    "latitude": 23.1256,
}


def _poi(provider_id: str, name: str, *, district: str = "越秀区") -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=113.31, latitude=23.13),
        type_name="风景名胜",
        type_code="110000",
        province="广东省",
        city="广州市",
        district=district,
        address=f"{name}地址",
    )


class StaticMapProvider:
    def __init__(self, pois: tuple[Poi, ...], *, by_id: dict[str, Poi] | None = None) -> None:
        self._pois = pois
        self._by_id = by_id or {}

    async def search_pois(self, request: object):
        keyword = request.keyword
        if keyword == "广州站":
            return self._success((_poi("anchor-station", "广州站"),))
        if keyword == "广州南站":
            return self._success((_poi("anchor-station-south", "广州南站"),))
        if keyword == "陈家祠":
            # Structured searches recall the exact-id POI when present;
            # otherwise name-matched candidates (like a real provider).
            if self._by_id:
                return self._success(tuple(self._by_id.values()))
            return self._success(tuple(poi for poi in self._pois if "陈家祠" in poi.name))
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


class SuccessfulRouteProvider:
    async def get_route(self, request: object):
        return ProviderSuccess(
            data=RoutePlan(
                mode="WALKING",
                distance_meters=1200,
                duration_seconds=900,
                steps=(
                    RouteStep(
                        instruction="Walk",
                        distance_meters=1200,
                        duration_seconds=900,
                        polyline=(request.origin, request.destination),
                    ),
                ),
                polyline=(request.origin, request.destination),
            ),
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 7, 23, tzinfo=UTC),
            estimated=False,
        )


def _command(
    *,
    arrival: dict | None = None,
    departure: dict | None = None,
    accommodation: dict | None = None,
    must_visit: list[str] | None = None,
    must_visit_refs: list[dict] | None = None,
) -> object:
    from trip_agent.worker.contracts import PlanningCreateCommand

    constraints = {
        "budgetAmount": 1000,
        "travelers": 1,
        "travelerType": "SOLO",
        "pace": "BALANCED",
        "preferences": ["历史"],
        "fixedSchedules": [],
        "arrival": arrival,
        "departure": departure,
        "accommodation": accommodation,
        "mustVisitPlaces": must_visit or [],
        "avoidPlaces": [],
        "mustVisitPlaceRefs": must_visit_refs or [],
        "avoidPlaceRefs": [],
        "mealWindows": [],
        "mobilityLevel": "STANDARD",
        "schemaVersion": 3 if (must_visit_refs or (arrival or {}).get("placeRef")) else 2,
    }
    return PlanningCreateCommand.model_validate(
        {
            "eventType": "PLANNING_CREATE_REQUESTED",
            "schemaVersion": 4,
            "eventId": "11111111-1111-4111-8111-111111111111",
            "traceId": "22222222-2222-4222-8222-222222222222",
            "taskId": "33333333-3333-4333-8333-333333333333",
            "tripId": "44444444-4444-4444-8444-444444444444",
            "occurredAt": "2026-07-31T02:00:00Z",
            "payload": {
                "taskType": "CREATE",
                "baselineTripVersion": 0,
                "idempotencyKey": "55555555-5555-4555-8555-555555555555",
                "trip": {
                    "title": "R5",
                    "destination": "广州",
                    "startDate": "2026-08-01",
                    "endDate": "2026-08-01",
                    "status": "DRAFT",
                    "version": 0,
                    "arrivalAt": "2026-08-01T08:00:00+08:00",
                    "departureAt": "2026-08-01T20:00:00+08:00",
                    "constraints": constraints,
                },
                "guideEvidence": {"facts": []},
                "planningContext": {
                    "snapshotId": "66666666-6666-4666-8666-666666666666",
                    "schemaVersion": 3,
                    "tripId": "44444444-4444-4444-8444-444444444444",
                    "planningTaskId": "33333333-3333-4333-8333-333333333333",
                    "city": "广州",
                    "travelStartDate": "2026-08-01",
                    "travelEndDate": "2026-08-01",
                    "generatedAt": "2026-07-31T02:00:00Z",
                    "stale": False,
                    "sources": [],
                    "facts": [],
                    "conflicts": [],
                    "excludedFacts": [],
                    "diagnostics": [],
                },
            },
        }
    )


def _provider(pois: tuple[Poi, ...], *, by_id: dict[str, Poi] | None = None):
    return AmapPlanningProvider(
        StaticMapProvider(pois, by_id=by_id),
        SuccessfulRouteProvider(),
    )


# ── R5.1: structured anchor binds exact provider id ─────────────────────────


def test_structured_arrival_anchor_pins_exact_provider_poi_id() -> None:
    """A recalled POI whose id equals the ref id is the anchor even when the
    recalled title carries a suffix the text matcher would reject."""
    by_id = {"B001234567": _poi("B001234567", "陈家祠(正门)")}
    result = asyncio.run(
        _provider((_poi("p1", "越秀公园"),), by_id=by_id).plan(
            _command(
                arrival={
                    "placeName": "陈家祠",
                    "time": "2026-08-01T11:00:00+08:00",
                    "placeRef": AMAP_REF,
                }
            )
        )
    )
    arrival_activity = next(
        a for day in result.itinerary.days for a in day.activities if a.kind == "ARRIVAL"
    )
    assert arrival_activity.provider_poi_id == "B001234567"


def test_structured_anchor_id_miss_fails_closed_never_same_name() -> None:
    """The exact id is not recalled; a same-name POI must NOT be used as the
    anchor (the old first-name-match fallback)."""
    by_id = {}  # no exact-id POI; only a same-name candidate with a different id
    with pytest.raises(PlanningInfeasibleError) as exc_info:
        asyncio.run(
            _provider((_poi("other-id", "陈家祠"), _poi("p1", "越秀公园")), by_id=by_id).plan(
                _command(
                    arrival={
                        "placeName": "陈家祠",
                        "time": "2026-08-01T11:00:00+08:00",
                        "placeRef": AMAP_REF,
                    }
                )
            )
        )
    codes = {conflict.code for conflict in exc_info.value.conflicts}
    assert "TRAVEL_ANCHOR_UNAVAILABLE" in codes


def test_legacy_text_anchor_keeps_name_resolution() -> None:
    """Without a ref, name-based resolution still works (unchanged)."""
    result = asyncio.run(
        _provider((_poi("p1", "越秀公园"),)).plan(
            _command(arrival={"placeName": "广州站", "time": "2026-08-01T11:00:00+08:00"})
        )
    )
    arrival_activity = next(
        a for day in result.itinerary.days for a in day.activities if a.kind == "ARRIVAL"
    )
    assert arrival_activity.provider_poi_id == "anchor-station"


# ── R5.2: structured must-visit binds by exact id only ──────────────────────


def test_structured_must_visit_binds_exact_id_with_suffixed_title() -> None:
    by_id = {"B001234567": _poi("B001234567", "陈家祠(正门)")}
    result = asyncio.run(
        _provider((_poi("p1", "越秀公园"),), by_id=by_id).plan(
            _command(must_visit=["陈家祠"], must_visit_refs=[AMAP_REF])
        )
    )
    placed_ids = {
        a.provider_poi_id
        for day in result.itinerary.days
        for a in day.activities
        if a.kind in {"ATTRACTION", "EXPERIENCE"}
    }
    assert "B001234567" in placed_ids


def test_structured_must_visit_id_miss_is_pinned_from_server_ref() -> None:
    """The exact id is missing from every search page.  B13_FIX.2 R9: the
    server-signed ref is a fixed planning input — the exact providerPoiId is
    pinned and placed; a same-name POI must never be bound as the must-visit
    place instead (exact identity is preserved, not weakened)."""
    pois = (_poi("same-name", "陈家祠"), _poi("p1", "越秀公园"))
    result = asyncio.run(
        _provider(pois, by_id={}).plan(_command(must_visit=["陈家祠"], must_visit_refs=[AMAP_REF]))
    )
    placed_ids = {
        a.provider_poi_id
        for day in result.itinerary.days
        for a in day.activities
        if a.kind in {"ATTRACTION", "EXPERIENCE"}
    }
    assert AMAP_REF["providerPoiId"] in placed_ids
    # The same-name sibling is not the must-visit place.
    provider = _provider(pois, by_id={})
    assert (
        provider._is_must_visit_poi(
            _poi("same-name", "陈家祠"), {"陈家祠"}, {AMAP_REF["providerPoiId"]}
        )
        is False
    )


def test_structured_must_visit_never_binds_same_name_sibling() -> None:
    """A/B same-name places: when the exact id IS recalled, the other
    same-name POI must not be treated as the must-visit place."""
    by_id = {"B001234567": _poi("B001234567", "陈家祠(正门)")}
    pois = (_poi("same-name", "陈家祠"), _poi("p1", "越秀公园"))
    result = asyncio.run(
        _provider(pois, by_id=by_id).plan(
            _command(must_visit=["陈家祠"], must_visit_refs=[AMAP_REF])
        )
    )
    placed_ids = {
        a.provider_poi_id
        for day in result.itinerary.days
        for a in day.activities
        if a.kind in {"ATTRACTION", "EXPERIENCE"}
    }
    assert "B001234567" in placed_ids
    # The same-name sibling may appear as a plain attraction, but the
    # must-visit decision itself is exact-identity only.
    provider = _provider((_poi("p1", "越秀公园"),), by_id=by_id)
    assert (
        provider._is_must_visit_poi(_poi("B001234567", "陈家祠(正门)"), {"陈家祠"}, {"B001234567"})
        is True
    )
    assert (
        provider._is_must_visit_poi(_poi("same-name", "陈家祠"), {"陈家祠"}, {"B001234567"})
        is False
    )


def test_legacy_must_visit_keeps_name_text_matching() -> None:
    result = asyncio.run(
        _provider((_poi("legacy-1", "陈家祠"), _poi("p1", "越秀公园"))).plan(
            _command(must_visit=["陈家祠"])
        )
    )
    placed_ids = {
        a.provider_poi_id
        for day in result.itinerary.days
        for a in day.activities
        if a.kind in {"ATTRACTION", "EXPERIENCE"}
    }
    assert "legacy-1" in placed_ids
