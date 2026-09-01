"""B13_FIX.2 R9 — structured must-visit recall must never stop early.

RED scenarios (all fail on the pre-fix implementation):

- two structured must-visit refs where the FIRST keyword search already
  returns enough ordinary candidates: the second exact id only appears in
  its own keyword search, and the old early-return path never searches it,
  so the planner fails with MUST_VISIT_UNAVAILABLE although the place is
  reachable (runtime fact: "天河公园" was searched, "正佳广场" never was);
- an exact must-visit id that ranks below the selection cutoff must still
  enter the selected candidates (pinned must visits bypass the cutoff);
- a same-name POI with a different providerPoiId must never replace the
  user's exact id;
- a server-signed PlaceRef that the search page never repeats becomes a
  pinned planning candidate: it is placed with its exact providerPoiId
  while opening/duration stay UNKNOWN (no fake VERIFIED evidence).
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

TIANHE_PARK_REF = {
    "provider": "AMAP",
    "providerPoiId": "B001234567",
    "name": "天河公园",
    "address": "广州市天河区中山大道西",
    "province": "广东省",
    "city": "广州市",
    "district": "天河区",
    "longitude": 113.3612,
    "latitude": 23.1312,
}

ZHENGJIA_REF = {
    "provider": "AMAP",
    "providerPoiId": "B00140TFHO",
    "name": "正佳广场",
    "address": "广州市天河区天河路228号",
    "province": "广东省",
    "city": "广州市",
    "district": "天河区",
    "longitude": 113.3263,
    "latitude": 23.1328,
}


def _poi(provider_id: str, name: str, *, district: str = "天河区") -> Poi:
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


class KeywordMapProvider:
    """Keyword-routed search: each keyword returns its own batch, exactly like
    a real provider where the exact must-visit id may only appear in the
    search for ITS OWN name."""

    def __init__(self, batches: dict[str, tuple[Poi, ...]]) -> None:
        self._batches = batches
        self.calls: list[str] = []

    async def search_pois(self, request: object):
        self.calls.append(request.keyword)
        return self._success(self._batches.get(request.keyword, ()))

    @staticmethod
    def _success(pois: tuple[Poi, ...]) -> ProviderSuccess[tuple[Poi, ...]]:
        return ProviderSuccess(
            data=pois,
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 8, 10, tzinfo=UTC),
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
            fetched_at=datetime(2026, 8, 10, tzinfo=UTC),
            estimated=False,
        )


def _command(
    must_visit: list[str],
    must_visit_refs: list[dict],
    *,
    arrival: str = "2026-08-20T08:00:00+08:00",
    departure: str = "2026-08-20T20:00:00+08:00",
) -> object:
    from trip_agent.worker.contracts import PlanningCreateCommand

    return PlanningCreateCommand.model_validate(
        {
            "eventType": "PLANNING_CREATE_REQUESTED",
            "schemaVersion": 4,
            "eventId": "11111111-1111-4111-8111-111111111111",
            "traceId": "22222222-2222-4222-8222-222222222222",
            "taskId": "33333333-3333-4333-8333-333333333333",
            "tripId": "44444444-4444-4444-8444-444444444444",
            "occurredAt": "2026-08-10T02:00:00Z",
            "payload": {
                "taskType": "CREATE",
                "baselineTripVersion": 0,
                "idempotencyKey": "55555555-5555-4555-8555-555555555555",
                "trip": {
                    "title": "R9",
                    "destination": "广州",
                    "startDate": "2026-08-20",
                    "endDate": "2026-08-20",
                    "status": "DRAFT",
                    "version": 0,
                    "arrivalAt": arrival,
                    "departureAt": departure,
                    "constraints": {
                        "budgetAmount": 1000,
                        "travelers": 1,
                        "travelerType": "SOLO",
                        "pace": "BALANCED",
                        "preferences": ["历史"],
                        "fixedSchedules": [],
                        "arrival": None,
                        "departure": None,
                        "accommodation": None,
                        "mustVisitPlaces": must_visit,
                        "avoidPlaces": [],
                        "mustVisitPlaceRefs": must_visit_refs,
                        "avoidPlaceRefs": [],
                        "mealWindows": [],
                        "mobilityLevel": "STANDARD",
                        "schemaVersion": 3,
                    },
                },
                "guideEvidence": {"facts": []},
                "planningContext": {
                    "snapshotId": "66666666-6666-4666-8666-666666666666",
                    "schemaVersion": 3,
                    "tripId": "44444444-4444-4444-8444-444444444444",
                    "planningTaskId": "33333333-3333-4333-8333-333333333333",
                    "city": "广州",
                    "travelStartDate": "2026-08-20",
                    "travelEndDate": "2026-08-20",
                    "generatedAt": "2026-08-10T02:00:00Z",
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


def _provider(map_provider: KeywordMapProvider) -> AmapPlanningProvider:
    return AmapPlanningProvider(
        map_provider,
        SuccessfulRouteProvider(),
    )


def _placed_ids(result) -> set[str]:
    return {
        activity.provider_poi_id
        for day in result.itinerary.days
        for activity in day.activities
        if activity.provider_poi_id is not None
    }


def _ordinary_pois(count: int = 4) -> tuple[Poi, ...]:
    return tuple(_poi(f"ordinary-{index}", f"普通候选{index}") for index in range(count))


# ── R9.1: first query already satisfies the count, second ref must still be
#          searched (exact id only appears in its own keyword search) ────────


def test_second_structured_ref_is_searched_even_when_first_query_satisfies_count() -> None:
    """The first keyword ("天河公园") returns enough ordinary candidates; the
    second exact id ("正佳广场" B00140TFHO) only appears in ITS OWN search.
    The planner must keep searching and must NOT fail with
    MUST_VISIT_UNAVAILABLE due to an early return."""
    map_provider = KeywordMapProvider(
        {
            "天河公园": (
                _poi(TIANHE_PARK_REF["providerPoiId"], "天河公园"),
                *_ordinary_pois(3),
            ),
            "正佳广场": (_poi(ZHENGJIA_REF["providerPoiId"], "正佳广场(天河路)"),),
        }
    )
    result = asyncio.run(
        _provider(map_provider).plan(
            _command(["天河公园", "正佳广场"], [TIANHE_PARK_REF, ZHENGJIA_REF])
        )
    )
    placed = _placed_ids(result)
    assert ZHENGJIA_REF["providerPoiId"] in placed
    assert TIANHE_PARK_REF["providerPoiId"] in placed
    # The second keyword must have been searched at all.
    assert "正佳广场" in map_provider.calls


# ── R9.2: exact id below the ranking cutoff still enters selected candidates ─


def test_exact_must_visit_id_below_cutoff_is_pinned_into_selected() -> None:
    """The exact id is recalled but ranks below the ordinary cutoff (suffixed
    title, no preference text).  A pinned must visit must still be selected —
    the ordinary quota must never delete a pinned item."""
    map_provider = KeywordMapProvider(
        {
            "天河公园": (
                _poi(TIANHE_PARK_REF["providerPoiId"], "天河公园"),
                *_ordinary_pois(6),
            ),
            "正佳广场": (_poi(ZHENGJIA_REF["providerPoiId"], "正佳广场(西北门)"),),
        }
    )
    result = asyncio.run(
        _provider(map_provider).plan(
            _command(["天河公园", "正佳广场"], [TIANHE_PARK_REF, ZHENGJIA_REF])
        )
    )
    placed = _placed_ids(result)
    assert ZHENGJIA_REF["providerPoiId"] in placed
    assert TIANHE_PARK_REF["providerPoiId"] in placed


# ── R9.3: same-name different-id must never replace the exact id ────────────


def test_same_name_different_id_never_replaces_exact_must_visit_id() -> None:
    """The search page returns a same-name POI ("正佳广场" with a different
    id) but never the exact id.  The server-signed ref is a fixed planning
    input: the exact id is pinned and placed; the sibling is NOT the
    must-visit place."""
    map_provider = KeywordMapProvider(
        {
            "天河公园": (
                _poi(TIANHE_PARK_REF["providerPoiId"], "天河公园"),
                *_ordinary_pois(3),
            ),
            "正佳广场": (_poi("same-name-sibling", "正佳广场"),),
        }
    )
    result = asyncio.run(
        _provider(map_provider).plan(
            _command(["天河公园", "正佳广场"], [TIANHE_PARK_REF, ZHENGJIA_REF])
        )
    )
    placed = _placed_ids(result)
    assert ZHENGJIA_REF["providerPoiId"] in placed
    # The sibling may appear as an ordinary attraction, but the must-visit
    # identity itself is the exact id — assert via the candidate mapping.
    provider = _provider(map_provider)
    assert (
        provider._is_must_visit_poi(
            _poi("same-name-sibling", "正佳广场"),
            {"天河公园", "正佳广场"},
            {ZHENGJIA_REF["providerPoiId"]},
        )
        is False
    )


# ── R9.4: unrecalled server-signed ref is pinned with UNKNOWN evidence ──────


def test_unrecalled_ref_is_pinned_without_fake_verified_evidence() -> None:
    """Neither search returns the exact id.  The ref must become a pinned
    candidate (placed with its exact providerPoiId) and the validation
    projection must NOT carry any opening evidence for it — UNKNOWN stays
    UNKNOWN, never a fabricated VERIFIED binding."""
    map_provider = KeywordMapProvider(
        {
            "天河公园": (
                _poi(TIANHE_PARK_REF["providerPoiId"], "天河公园"),
                *_ordinary_pois(3),
            ),
            # "正佳广场" search returns nothing for the exact id.
            "正佳广场": (_poi("unrelated", "正佳广场服务中心"),),
        }
    )
    result = asyncio.run(
        _provider(map_provider).plan(
            _command(["天河公园", "正佳广场"], [TIANHE_PARK_REF, ZHENGJIA_REF])
        )
    )
    placed = _placed_ids(result)
    assert ZHENGJIA_REF["providerPoiId"] in placed
    assert TIANHE_PARK_REF["providerPoiId"] in placed
    # No opening-hours evidence may exist for the pinned id.
    pinned_bindings = [
        binding
        for binding in result.validation_inputs.opening_hours_bindings
        if binding.poi_key == ZHENGJIA_REF["providerPoiId"]
    ]
    assert pinned_bindings == []


# ── R11: duplicate exact ids stay stably deduplicated ───────────────────────


def test_duplicate_structured_ids_are_deduplicated_stably() -> None:
    """Two structured refs carrying the SAME providerPoiId (user picked the
    same place twice) must produce exactly one pinned candidate and one
    placed activity — never a duplicate, and the plan still succeeds."""
    duplicated_ref = {**ZHENGJIA_REF}
    map_provider = KeywordMapProvider(
        {
            "天河公园": (
                _poi(TIANHE_PARK_REF["providerPoiId"], "天河公园"),
                *_ordinary_pois(3),
            ),
            "正佳广场": (_poi(ZHENGJIA_REF["providerPoiId"], "正佳广场(天河路)"),),
        }
    )
    result = asyncio.run(
        _provider(map_provider).plan(
            _command(
                ["天河公园", "正佳广场", "正佳广场"],
                [TIANHE_PARK_REF, ZHENGJIA_REF, duplicated_ref],
            )
        )
    )
    occurrences = [
        activity.provider_poi_id
        for day in result.itinerary.days
        for activity in day.activities
        if activity.provider_poi_id == ZHENGJIA_REF["providerPoiId"]
    ]
    assert len(occurrences) == 1
    assert TIANHE_PARK_REF["providerPoiId"] in _placed_ids(result)


# ── MUST_VISIT_UNAVAILABLE stays reserved for genuine failures ──────────────


def test_tight_fixed_departure_still_fails_closed_when_must_visit_cannot_fit() -> None:
    """A must visit that genuinely cannot be placed within the day (here: a
    60-minute window after 18:00 arrival — no ordinary visit fits) must
    still fail closed.  Recall misses are pinned; real time-constraint
    failures are not papered over."""
    map_provider = KeywordMapProvider(
        {
            "天河公园": (
                _poi(TIANHE_PARK_REF["providerPoiId"], "天河公园"),
                *_ordinary_pois(3),
            ),
            "正佳广场": (),
        }
    )
    with pytest.raises(PlanningInfeasibleError) as exc_info:
        asyncio.run(
            _provider(map_provider).plan(
                _command(
                    ["天河公园", "正佳广场"],
                    [TIANHE_PARK_REF, ZHENGJIA_REF],
                    arrival="2026-08-20T18:00:00+08:00",
                    departure="2026-08-20T19:00:00+08:00",
                )
            )
        )
    codes = {conflict.code for conflict in exc_info.value.conflicts}
    # The authoritative departure boundary now catches the impossible route
    # before the later must-visit recall audit.
    assert "INSUFFICIENT_DAY_CAPACITY" in codes


def test_filtered_structured_must_visit_explains_that_user_should_reselect() -> None:
    """A signed ref can still describe infrastructure such as a metro stop.

    That is not a must/avoid contradiction.  The failure shown to the user
    must identify the unusable selection and tell them to choose the actual
    attraction instead of suggesting unrelated constraint relaxation.
    """
    station_ref = {
        **TIANHE_PARK_REF,
        "providerPoiId": "B-METRO",
        "name": "陈家祠(地铁站)",
        "address": "陈家祠地铁站",
        "district": "荔湾区",
    }
    station = _poi("B-METRO", "陈家祠(地铁站)", district="荔湾区").model_copy(
        update={
            "type_name": "交通设施服务;地铁站;地铁站",
            "type_code": "150500",
        }
    )
    map_provider = KeywordMapProvider({"陈家祠(地铁站)": (station, *_ordinary_pois(3))})

    with pytest.raises(PlanningInfeasibleError) as exc_info:
        asyncio.run(_provider(map_provider).plan(_command(["陈家祠(地铁站)"], [station_ref])))

    conflict = exc_info.value.conflicts[0]
    assert conflict.code == "MUST_VISIT_UNAVAILABLE"
    assert conflict.message == "所选必去地点不是可安排的景点，或当前地图资料无法确认"
    assert (
        exc_info.value.relaxations[0].message
        == "请重新搜索并选择景点本身，不要选择地铁站、出入口或停车场"
    )
