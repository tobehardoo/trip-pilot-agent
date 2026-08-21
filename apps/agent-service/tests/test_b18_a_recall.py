"""B18-A — must-visit exact identity + candidate recall early-stop fix.

RED scenarios for the two confirmed root causes:

- P18-R3: ``MUST_VISIT_MATCH`` used substring matching, so sibling POIs whose
  name/address merely *contain* the must-visit text (e.g. 小林蓝鳄正佳广场)
  received the same +100 boost as the exact place.  B18-A makes the boost an
  exact-identity match: ``providerPoiId`` when structured refs exist, else
  normalized exact-name equality (legacy free text).
- P18-R2: ``_collect_pois`` stopped the keyword recall loop as soon as the
  ordinary candidate count was reached, so a must-visit keyword that returned
  enough nearby POIs silently skipped every later exploration keyword.

The must-visit place stays a hard planning input: the exact id must survive
ranking (pinned), and structured ref integrity checks are preserved.
"""

import asyncio
from datetime import UTC, datetime

from trip_agent.domain.shared import candidate_keywords
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.planning.candidates import CandidateRanker
from trip_agent.providers.map import Coordinates, Poi, ProviderSuccess
from trip_agent.providers.route import RoutePlan, RouteStep

ZHENGJIA_ID = "B00140TFHO"
ZHENGJIA_REF = {
    "provider": "AMAP",
    "providerPoiId": ZHENGJIA_ID,
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


def _rank(pois, *, must_visit_places, must_visit_provider_ids=frozenset(), **kwargs):
    return CandidateRanker().rank(
        tuple(pois),
        destination="广州",
        preferences=(),
        traveler_type="SOLO",
        limit=len(pois),
        must_visit_places=tuple(must_visit_places),
        must_visit_provider_ids=frozenset(must_visit_provider_ids),
        **kwargs,
    )


# ── A1 — structured exact identity must match ────────────────────────────────


def test_a1_structured_exact_identity_gets_must_visit_boost() -> None:
    """must_visit 正佳广场/B00140TFHO; candidate 正佳广场/B00140TFHO must hit
    MUST_VISIT_MATCH and receive the strong must-visit weight."""
    result = _rank(
        (_poi(ZHENGJIA_ID, "正佳广场"),),
        must_visit_places=("正佳广场",),
        must_visit_provider_ids=(ZHENGJIA_ID,),
    )
    item = result.selected[0]
    assert any(reason.startswith("MUST_VISIT_MATCH:") for reason in item.reasons)
    assert item.score >= 120


# ── A2 — substring sibling must NOT get the boost ─────────────────────────────


def test_a2_substring_sibling_gets_no_must_visit_boost() -> None:
    """candidate 小林蓝鳄正佳广场/OTHER_ID contains the must-visit text but has
    a different providerPoiId — it must be an ordinary candidate, not a
    must-visit, and it must NOT be filtered away."""
    result = _rank(
        (
            _poi(ZHENGJIA_ID, "正佳广场"),
            _poi("B0MDA73DXY", "小林蓝鳄正佳广场"),
        ),
        must_visit_places=("正佳广场",),
        must_visit_provider_ids=(ZHENGJIA_ID,),
    )
    sibling = next(item for item in result.selected if item.poi.provider_id == "B0MDA73DXY")
    assert not any(reason.startswith("MUST_VISIT_MATCH:") for reason in sibling.reasons)
    assert sibling.score == 20  # base quality only, no +100


# ── A3 — same name, different id: provider identity wins ─────────────────────


def test_a3_same_name_different_id_is_not_must_visit_when_structured() -> None:
    """must_visit 正佳广场/B00140TFHO; candidate 正佳广场/OTHER_ID shares the
    exact display name but not the id.  In the structured path the exact name
    must NOT override the provider identity."""
    result = _rank(
        (_poi("OTHER_ID", "正佳广场"),),
        must_visit_places=("正佳广场",),
        must_visit_provider_ids=(ZHENGJIA_ID,),
    )
    item = result.selected[0]
    assert not any(reason.startswith("MUST_VISIT_MATCH:") for reason in item.reasons)
    assert item.score == 20


def test_a3_legacy_same_name_without_refs_is_exact_name_match() -> None:
    """Without structured refs the legacy name-only path keeps normalized exact
    name equality: 正佳广场 == 正佳广场 is still a must-visit."""
    result = _rank(
        (_poi("OTHER_ID", "正佳广场"),),
        must_visit_places=("正佳广场",),
    )
    item = result.selected[0]
    assert any(reason.startswith("MUST_VISIT_MATCH:") for reason in item.reasons)


# ── A4 — legacy exact-name matching ───────────────────────────────────────────


def test_a4_legacy_exact_name_matches_but_substring_does_not() -> None:
    """must_visit_places=["正佳广场"], must_visit_refs=[].  正佳广场 matches by
    normalized exact name; 小林蓝鳄正佳广场 does not."""
    result = _rank(
        (
            _poi("a", "正佳广场"),
            _poi("b", "小林蓝鳄正佳广场"),
        ),
        must_visit_places=("正佳广场",),
    )
    exact = next(item for item in result.selected if item.poi.provider_id == "a")
    sibling = next(item for item in result.selected if item.poi.provider_id == "b")
    assert any(reason.startswith("MUST_VISIT_MATCH:") for reason in exact.reasons)
    assert not any(reason.startswith("MUST_VISIT_MATCH:") for reason in sibling.reasons)


# ── integration helpers ───────────────────────────────────────────────────────


class KeywordMapProvider:
    def __init__(self, batches: dict[str, tuple[Poi, ...]]) -> None:
        self._batches = batches
        self.calls: list[str] = []

    async def search_pois(self, request: object):
        self.calls.append(request.keyword)
        return ProviderSuccess(
            data=self._batches.get(request.keyword, ()),
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
    preferences: list[str] | None = None,
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
                    "title": "B18-A",
                    "destination": "广州",
                    "startDate": "2026-08-20",
                    "endDate": "2026-08-20",
                    "status": "DRAFT",
                    "version": 0,
                    "arrivalAt": "2026-08-20T08:00:00+08:00",
                    "departureAt": "2026-08-20T20:00:00+08:00",
                    "constraints": {
                        "budgetAmount": 1000,
                        "travelers": 1,
                        "travelerType": "SOLO",
                        "pace": "BALANCED",
                        "preferences": preferences if preferences is not None else ["历史"],
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
    return AmapPlanningProvider(map_provider, SuccessfulRouteProvider())


def _placed_ids(result) -> set[str]:
    return {
        activity.provider_poi_id
        for day in result.itinerary.days
        for activity in day.activities
        if activity.provider_poi_id is not None
    }


def _ordinary_pois(count: int = 4) -> tuple[Poi, ...]:
    return tuple(_poi(f"ordinary-{index}", f"普通候选{index}") for index in range(count))


# ── A5 — keyword recall must not early-stop on must-visit query ───────────────


def test_a5_all_exploration_keywords_execute_after_must_visit_query() -> None:
    """The first keyword (正佳广场) returns enough candidates immediately.
    Pre-fix behaviour stops the recall loop right after the first must-visit
    keyword; the fix must execute every allowed keyword (MAX_POI_QUERIES)."""
    preferences = ("历史", "城市地标")
    keywords = candidate_keywords(preferences, ("正佳广场",))
    assert "城市地标" in keywords and "博物馆" in keywords and "公园" in keywords

    map_provider = KeywordMapProvider(
        {
            "正佳广场": (_poi(ZHENGJIA_ID, "正佳广场"), *_ordinary_pois(5)),
            "历史": (_poi("kw-history", "南越王博物馆"),),
            "城市地标": (_poi("kw-landmark", "广州塔"),),
            "景点": (_poi("kw-scenic", "沙面岛"),),
            "博物馆": (_poi("kw-museum", "广东省博物馆"),),
            "公园": (_poi("kw-park", "越秀公园"),),
        }
    )
    provider = _provider(map_provider)
    pool = asyncio.run(
        provider._collect_pois(
            _command(["正佳广场"], [ZHENGJIA_REF], preferences=list(preferences)),
            3,
        )
    )

    assert "正佳广场" in map_provider.calls
    # The must-visit keyword result may be large — later keywords must still run.
    assert len(map_provider.calls) == len(keywords)
    assert set(map_provider.calls) == set(keywords)
    # Exploration keywords contribute candidates to the pool.
    assert any(item.poi.provider_id == "kw-landmark" for item in pool)


# ── A6 — exact must-visit survives ordinary ranking ───────────────────────────


def test_a6_exact_must_visit_survives_ranking_after_boost_change() -> None:
    """The exact 正佳广场 must-visit has a deliberately low ordinary quality
    score (suffixed title, no preference match).  After removing the substring
    boost it must still be selected — required semantics stay intact."""
    map_provider = KeywordMapProvider(
        {
            "正佳广场": (
                _poi(ZHENGJIA_ID, "正佳广场(西北门)"),
                _poi("sib-1", "小林蓝鳄正佳广场"),
                _poi("sib-2", "广州正佳广场万豪酒店"),
            ),
            "历史": (_poi("kw-history", "南越王博物馆"),),
            "城市地标": (_poi("kw-landmark", "广州塔"),),
            "景点": (_poi("kw-scenic", "沙面岛"),),
            "博物馆": (_poi("kw-museum", "广东省博物馆"),),
            "公园": (_poi("kw-park", "越秀公园"),),
        }
    )
    result = asyncio.run(
        _provider(map_provider).plan(
            _command(["正佳广场"], [ZHENGJIA_REF], preferences=["历史", "城市地标"])
        )
    )
    placed = _placed_ids(result)
    assert ZHENGJIA_ID in placed


# ── A7 — candidate pool keeps both exact must-visit and exploration sources ───


def test_a7_candidate_pool_contains_exact_must_visit_and_exploration_candidates() -> None:
    """must_visit keyword returns a large sibling batch; exploration keywords
    return museum / park / landmark / history candidates.  The GREEN pool must
    contain the exact must-visit AND normal city-wide exploration candidates."""
    preferences = ("历史", "城市地标")
    keywords = candidate_keywords(preferences, ("正佳广场",))
    map_provider = KeywordMapProvider(
        {
            "正佳广场": (
                _poi(ZHENGJIA_ID, "正佳广场"),
                _poi("sib-1", "小林蓝鳄正佳广场"),
                _poi("sib-2", "广州正佳广场万豪酒店"),
                _poi("sib-3", "广正烧(正佳广场店)"),
            ),
            "历史": (_poi("kw-history", "南越王博物馆"),),
            "城市地标": (_poi("kw-landmark", "广州塔"),),
            "景点": (_poi("kw-scenic", "沙面岛"),),
            "博物馆": (_poi("kw-museum", "广东省博物馆"),),
            "公园": (_poi("kw-park", "越秀公园"),),
        }
    )
    provider = _provider(map_provider)
    pool = asyncio.run(
        provider._collect_pois(
            _command(["正佳广场"], [ZHENGJIA_REF], preferences=list(preferences)),
            3,
        )
    )
    pool_ids = {item.poi.provider_id for item in pool}
    # Exact must-visit is recalled.
    assert ZHENGJIA_ID in pool_ids
    # Exploration sources actually executed and contributed to the pool.
    assert set(map_provider.calls) == set(keywords)
    assert any(
        poi_id in pool_ids for poi_id in ("kw-history", "kw-landmark", "kw-museum", "kw-park")
    )
