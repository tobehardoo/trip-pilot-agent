import asyncio
import json
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_planning_worker import COMMAND

from trip_agent.planning.candidates import CandidateRanker
from trip_agent.planning.optimization import DailyOptimizationRequest, DailyOptimizer, TimeBlock
from trip_agent.providers.map import Coordinates, Poi, ProviderSuccess
from trip_agent.providers.route import RoutePlan, RouteStep
from trip_agent.worker.contracts import (
    KnowledgeCitationSnapshot,
    KnowledgeEvidence,
    KnowledgeFreshness,
    PlanningCreateCommand,
)
from trip_agent.worker.processor import (
    AmapPlanningProvider,
    DemoPlanningProvider,
    FallbackPlanningProvider,
    PlanningInfeasibleError,
    PlanningProviderError,
    PlanningResult,
    process_planning_create,
)

CHINA_TIME_ZONE = timezone(timedelta(hours=8))


def _v2_command() -> dict:
    payload = deepcopy(COMMAND)
    payload["schemaVersion"] = 2
    payload["payload"]["trip"]["endDate"] = "2026-08-02"
    payload["payload"]["trip"]["constraints"].update(
        {
            "schemaVersion": 2,
            "arrival": {
                "placeName": "广州南站",
                "time": "2026-08-01T11:00:00+08:00",
            },
            "departure": {
                "placeName": "广州白云机场",
                "time": "2026-08-02T17:00:00+08:00",
            },
            "accommodation": {"placeName": "北京路附近酒店"},
            "mustVisitPlaces": ["陈家祠"],
            "avoidPlaces": ["广州塔"],
            "mealWindows": [
                {"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00"}
            ],
            "mobilityLevel": "REDUCED",
        }
    )
    payload["payload"]["guideEvidence"] = {
        "facts": [
            {
                "guideImportId": "bcb83ab0-4ca0-40e8-8970-aae97c2a1162",
                "factId": "4c0c1707-2264-408e-8308-c5ca6816c80a",
                "category": "ATTRACTION",
                "statement": "陈家祠上午人少，适合优先安排。",
                "evidence": "建议上午前往陈家祠。",
                "sourceUrl": "https://example.com/guangzhou",
                "sourceHost": "example.com",
                "sourceTitle": "广州周末攻略",
                "confidence": 0.84,
                "observedAt": "2026-07-13T08:00:00Z",
                "expiresAt": "2026-08-03T08:00:00Z",
            }
        ]
    }
    return payload


def _poi(provider_id: str, name: str) -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=113.26, latitude=23.13),
        type_name="风景名胜",
        type_code="110000",
        province="广东省",
        city="广州市",
        district="越秀区",
        address=f"{name}地址",
    )


def _local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, datetime.min.time(), CHINA_TIME_ZONE).replace(
        hour=hour, minute=minute
    )


def _route_success(request: object, *, distance: int = 600, duration: int = 600):
    return ProviderSuccess(
        data=RoutePlan(
            mode=request.mode,
            distance_meters=distance,
            duration_seconds=duration,
            steps=(
                RouteStep(
                    instruction="Transfer",
                    distance_meters=distance,
                    duration_seconds=duration,
                    polyline=(request.origin, request.destination),
                ),
            ),
            polyline=(request.origin, request.destination),
        ),
        provider="AMAP",
        latency_ms=1,
        cached=False,
        fetched_at=datetime(2026, 7, 14, tzinfo=UTC),
        estimated=False,
    )


def test_v2_contract_parses_context_and_guide_evidence() -> None:
    command = PlanningCreateCommand.model_validate(_v2_command())

    constraints = command.payload.trip.constraints
    assert constraints.arrival.place_name == "广州南站"
    assert constraints.departure.time.isoformat() == "2026-08-02T17:00:00+08:00"
    assert constraints.must_visit_places == ("陈家祠",)
    assert constraints.mobility_level == "REDUCED"
    assert command.payload.guide_evidence.facts[0].statement.startswith("陈家祠")

    schema = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "contracts/messaging/planning-create-command-v2.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(_v2_command())


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("arrival", "time"), "2026-07-31T23:00:00+08:00"),
        (("departure", "time"), "2026-08-03T10:00:00+08:00"),
        (("mealWindows", 0, "endTime"), "11:59"),
    ],
)
def test_v2_contract_rejects_invalid_context_ranges(
    path: tuple[str | int, ...], value: str
) -> None:
    payload = _v2_command()
    target: object = payload["payload"]["trip"]["constraints"]
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        PlanningCreateCommand.model_validate(payload)


def test_ranker_filters_avoided_places_and_softly_boosts_guide_matches() -> None:
    result = CandidateRanker().rank(
        (
            _poi("tower", "广州塔"),
            _poi("chen", "陈家祠"),
            _poi("park", "越秀公园"),
        ),
        destination="广州",
        preferences=(),
        traveler_type="FRIENDS",
        limit=2,
        must_visit_places=("陈家祠",),
        avoid_places=("广州塔",),
        guide_statements=("陈家祠上午人少，适合优先安排。",),
    )

    assert [item.poi.provider_id for item in result.selected] == ["chen", "park"]
    assert "MUST_VISIT_MATCH:陈家祠" in result.selected[0].reasons
    assert "GUIDE_FACT_MATCH" in result.selected[0].reasons
    assert ("tower", "AVOID_PLACE") in [
        (item.poi.provider_id, item.reason) for item in result.rejected
    ]


def test_ranker_guarantees_available_must_visit_before_higher_scoring_optional() -> None:
    must_visit = _poi("must", "Must Museum")
    optional = _poi("optional", "Food History Architecture Center")

    result = CandidateRanker().rank(
        (optional, must_visit),
        destination="广州",
        preferences=("Food", "History", "Architecture"),
        traveler_type="FRIENDS",
        limit=1,
        must_visit_places=("Must Museum",),
    )

    assert [item.poi.provider_id for item in result.selected] == ["must"]


@pytest.mark.parametrize(
    "statement",
    (
        "Crowded Tower 排队很久，不推荐去",
        "Crowded Tower 不值得去",
        "Crowded Tower 不适合家庭",
        "Crowded Tower 不方便而且不好吃",
    ),
)
def test_ranker_does_not_promote_negative_guide_mentions(statement: str) -> None:
    result = CandidateRanker().rank(
        (_poi("negative", "Crowded Tower"), _poi("neutral", "Quiet Park")),
        destination="广州",
        preferences=(),
        traveler_type="FRIENDS",
        limit=2,
        guide_statements=(statement,),
    )

    negative = next(item for item in result.selected if item.poi.provider_id == "negative")
    assert "GUIDE_FACT_MATCH" not in negative.reasons


def test_provider_fallback_does_not_bypass_v2_must_visit_constraint() -> None:
    command = PlanningCreateCommand.model_validate(_v2_command())

    class FailedPrimary:
        async def plan(self, received: PlanningCreateCommand) -> PlanningResult:
            del received
            raise PlanningProviderError("PROVIDER_UNAVAILABLE")

    provider = FallbackPlanningProvider(FailedPrimary(), DemoPlanningProvider())

    with pytest.raises(PlanningInfeasibleError, match="必去"):
        asyncio.run(provider.plan(command))


def test_demo_fallback_respects_arrival_departure_and_meal_windows() -> None:
    payload = _v2_command()
    payload["payload"]["trip"]["endDate"] = "2026-08-01"
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["arrival"] = {
        "placeName": "Station",
        "time": "2026-08-01T14:00:00+08:00",
    }
    constraints["departure"] = {
        "placeName": "Station",
        "time": "2026-08-01T18:00:00+08:00",
    }
    constraints["mustVisitPlaces"] = []
    constraints["avoidPlaces"] = []
    constraints["mealWindows"] = [
        {"mealType": "DINNER", "startTime": "15:00", "endTime": "16:00"}
    ]
    payload["payload"]["guideEvidence"]["facts"] = []
    command = PlanningCreateCommand.model_validate(payload)

    result = asyncio.run(DemoPlanningProvider().plan(command))

    activity = result.itinerary.days[0].activities[0]
    assert activity.start_time >= _local(date(2026, 8, 1), 16)
    assert activity.end_time <= _local(date(2026, 8, 1), 18)


def test_demo_fallback_respects_fixed_schedule_spanning_midnight() -> None:
    payload = _v2_command()
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["arrival"] = None
    constraints["departure"] = None
    constraints["accommodation"] = None
    constraints["mustVisitPlaces"] = []
    constraints["avoidPlaces"] = []
    constraints["mealWindows"] = [
        {"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00"}
    ]
    constraints["fixedSchedules"] = [{
        "placeName": "Overnight train",
        "startTime": "2026-08-01T23:00:00+08:00",
        "endTime": "2026-08-02T10:30:00+08:00",
    }]
    payload["payload"]["guideEvidence"]["facts"] = []
    command = PlanningCreateCommand.model_validate(payload)

    result = asyncio.run(DemoPlanningProvider().plan(command))

    second_day_activity = result.itinerary.days[1].activities[0]
    assert second_day_activity.start_time >= _local(date(2026, 8, 2), 13)


def test_optimizer_applies_arrival_departure_and_meal_windows() -> None:
    day = date(2026, 8, 1)
    result = DailyOptimizer().optimize(
        DailyOptimizationRequest(
            date=day,
            available_start_minute=11 * 60,
            available_end_minute=18 * 60,
            route_duration_seconds=30 * 60,
            fixed_schedules=(
                TimeBlock("午餐", _local(day, 12), _local(day, 13)),
            ),
        )
    )

    assert result.status == "FEASIBLE"
    assert result.first_start >= _local(day, 11)
    assert result.second_start >= _local(day, 13)
    assert result.second_end <= _local(day, 18)


def test_contract_uses_china_local_dates_after_java_serializes_anchors_as_utc() -> None:
    payload = _v2_command()
    payload["payload"]["trip"]["constraints"]["arrival"]["time"] = (
        "2026-07-31T17:00:00Z"
    )
    payload["payload"]["trip"]["constraints"]["departure"]["time"] = (
        "2026-08-01T17:00:00Z"
    )

    command = PlanningCreateCommand.model_validate(payload)

    assert command.payload.trip.constraints.arrival.time.isoformat().endswith("+00:00")


def test_contract_rejects_overlapping_meal_windows() -> None:
    payload = _v2_command()
    payload["payload"]["trip"]["constraints"]["mealWindows"] = [
        {"mealType": "BREAKFAST", "startTime": "08:00", "endTime": "10:00"},
        {"mealType": "LUNCH", "startTime": "09:30", "endTime": "11:00"},
    ]

    with pytest.raises(ValidationError, match="overlap"):
        PlanningCreateCommand.model_validate(payload)


def test_contract_rejects_trip_longer_than_bounded_planning_window() -> None:
    payload = _v2_command()
    payload["payload"]["trip"]["endDate"] = "2026-08-08"
    payload["payload"]["trip"]["constraints"]["departure"]["time"] = (
        "2026-08-08T17:00:00+08:00"
    )

    with pytest.raises(ValidationError, match="7 days"):
        PlanningCreateCommand.model_validate(payload)


@pytest.mark.parametrize(
    ("observed_at", "expires_at"),
    [
        ("2026-07-14T03:00:01Z", "2026-08-03T08:00:00Z"),
        ("2026-07-13T08:00:00Z", "2026-07-14T03:00:00Z"),
    ],
)
def test_contract_rejects_guide_facts_not_fresh_at_task_creation(
    observed_at: str,
    expires_at: str,
) -> None:
    payload = _v2_command()
    fact = payload["payload"]["guideEvidence"]["facts"][0]
    fact["observedAt"] = observed_at
    fact["expiresAt"] = expires_at

    with pytest.raises(ValidationError, match="fresh"):
        PlanningCreateCommand.model_validate(payload)


def test_guide_snapshot_is_merged_into_completed_knowledge_citations() -> None:
    payload = _v2_command()
    payload["payload"]["trip"]["constraints"]["mustVisitPlaces"] = []
    command = PlanningCreateCommand.model_validate(payload)

    class GuideAwareProvider:
        async def plan(self, received: PlanningCreateCommand) -> PlanningResult:
            base = await DemoPlanningProvider().plan(received)
            return PlanningResult(
                provider=base.provider,
                itinerary=base.itinerary,
                guide_fact_ids=(received.payload.guide_evidence.facts[0].fact_id,),
            )

    completed = asyncio.run(
        process_planning_create(
            command,
            GuideAwareProvider(),
            occurred_at=datetime(2026, 7, 23, 10, tzinfo=UTC),
        )
    )

    assert completed.payload.knowledge.status == "REAL"
    citation = completed.payload.knowledge.citations[0]
    assert citation.document_id == str(
        command.payload.guide_evidence.facts[0].guide_import_id
    )
    assert citation.chunk_id == str(command.payload.guide_evidence.facts[0].fact_id)
    assert str(citation.source_url) == "https://example.com/guangzhou"
    assert citation.reliability_level == "community-guide"
    assert command.payload.guide_evidence.facts[0].statement in citation.title
    assert completed.payload.knowledge.freshness.checked_at == datetime(
        2026, 7, 23, 10, tzinfo=UTC
    )


def test_step_free_uses_vehicle_routes_and_accounts_for_travel_anchors() -> None:
    payload = _v2_command()
    payload["payload"]["trip"]["endDate"] = "2026-08-01"
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["arrival"] = {
        "placeName": "Arrival Station",
        "time": "2026-08-01T10:00:00+08:00",
    }
    constraints["departure"] = {
        "placeName": "Departure Airport",
        "time": "2026-08-01T17:00:00+08:00",
    }
    constraints["accommodation"] = {"placeName": "Accessible Hotel"}
    constraints["mustVisitPlaces"] = []
    constraints["avoidPlaces"] = []
    constraints["mealWindows"] = []
    constraints["mobilityLevel"] = "STEP_FREE"
    payload["payload"]["guideEvidence"]["facts"] = []
    command = PlanningCreateCommand.model_validate(payload)
    anchors = {
        "Arrival Station": _poi("arrival", "Arrival Station"),
        "Departure Airport": _poi("departure", "Departure Airport"),
        "Accessible Hotel": _poi("hotel", "Accessible Hotel"),
    }
    candidates = (_poi("one", "Museum One"), _poi("two", "Museum Two"))

    class MapProvider:
        def __init__(self) -> None:
            self.keywords: list[str] = []

        async def search_pois(self, request: object):
            self.keywords.append(request.keyword)
            data = (anchors[request.keyword],) if request.keyword in anchors else candidates
            return ProviderSuccess(
                data=data,
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 7, 14, tzinfo=UTC),
                estimated=False,
            )

    class RouteProvider:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def get_route(self, request: object):
            self.requests.append(request)
            return _route_success(request)

    map_provider = MapProvider()
    route_provider = RouteProvider()
    result = asyncio.run(AmapPlanningProvider(map_provider, route_provider).plan(command))

    day = result.itinerary.days[0]
    assert {"Arrival Station", "Departure Airport", "Accessible Hotel"} <= set(
        map_provider.keywords
    )
    assert all(request.mode == "DRIVING" for request in route_provider.requests)
    assert day.activities[0].start_time >= _local(date(2026, 8, 1), 10, 10)
    assert day.activities[-1].end_time <= _local(date(2026, 8, 1), 16, 50)
    assert day.transit_legs[0].mode == "DRIVING"


def test_reduced_mobility_retries_after_guide_ranked_pair_is_too_far() -> None:
    payload = _v2_command()
    payload["payload"]["trip"]["endDate"] = "2026-08-01"
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["arrival"] = None
    constraints["departure"] = None
    constraints["accommodation"] = None
    constraints["mustVisitPlaces"] = []
    constraints["avoidPlaces"] = []
    constraints["mealWindows"] = []
    constraints["mobilityLevel"] = "REDUCED"
    constraints["preferences"] = []
    payload["payload"]["guideEvidence"]["facts"][0]["statement"] = (
        "Top One 和 Top Two 都值得优先推荐"
    )
    payload["payload"]["guideEvidence"]["facts"][0]["evidence"] = "Top One Top Two"
    command = PlanningCreateCommand.model_validate(payload)
    candidates = (
        _poi("top-one", "Top One"),
        _poi("top-two", "Top Two"),
        _poi("alternative", "Alternative"),
    )

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

    class RouteProvider:
        async def get_route(self, request: object):
            pair = {request.origin_poi_id, request.destination_poi_id}
            distance = 5_000 if pair == {"top-one", "top-two"} else 1_000
            return _route_success(request, distance=distance)

    result = asyncio.run(AmapPlanningProvider(MapProvider(), RouteProvider()).plan(command))

    selected = {
        activity.provider_poi_id
        for activity in result.itinerary.days[0].activities
    }
    assert selected != {"top-one", "top-two"}


def test_guide_fact_is_not_cited_when_it_does_not_change_the_baseline_plan() -> None:
    payload = _v2_command()
    payload["payload"]["trip"]["endDate"] = "2026-08-01"
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["arrival"] = None
    constraints["departure"] = None
    constraints["accommodation"] = None
    constraints["mustVisitPlaces"] = []
    constraints["avoidPlaces"] = []
    constraints["mealWindows"] = []
    constraints["mobilityLevel"] = "STANDARD"
    constraints["preferences"] = []
    fact = payload["payload"]["guideEvidence"]["facts"][0]
    fact["statement"] = "Alpha 推荐且值得优先安排"
    fact["evidence"] = "Alpha 推荐"
    command = PlanningCreateCommand.model_validate(payload)
    candidates = (_poi("alpha", "Alpha"), _poi("beta", "Beta"))

    class MapProvider:
        async def search_pois(self, request: object):
            del request
            return ProviderSuccess(
                data=candidates,
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 7, 14, tzinfo=UTC),
                estimated=False,
            )

    class RouteProvider:
        async def get_route(self, request: object):
            return _route_success(request)

    result = asyncio.run(AmapPlanningProvider(MapProvider(), RouteProvider()).plan(command))

    assert result.guide_fact_ids == ()


def test_multiday_planner_backtracks_when_first_feasible_pair_blocks_later_day() -> None:
    payload = _v2_command()
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["arrival"] = None
    constraints["departure"] = None
    constraints["accommodation"] = None
    constraints["mustVisitPlaces"] = []
    constraints["avoidPlaces"] = []
    constraints["mealWindows"] = []
    constraints["mobilityLevel"] = "REDUCED"
    constraints["preferences"] = []
    payload["payload"]["guideEvidence"]["facts"] = []
    command = PlanningCreateCommand.model_validate(payload)
    candidates = tuple(_poi(letter.lower(), letter) for letter in ("A", "B", "C", "D"))

    class MapProvider:
        async def search_pois(self, request: object):
            del request
            return ProviderSuccess(
                data=candidates,
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 7, 14, tzinfo=UTC),
                estimated=False,
            )

    class RouteProvider:
        async def get_route(self, request: object):
            pair = {request.origin_poi_id, request.destination_poi_id}
            feasible = pair in ({"a", "b"}, {"a", "c"}, {"b", "d"})
            return _route_success(request, distance=1_000 if feasible else 5_000)

    result = asyncio.run(AmapPlanningProvider(MapProvider(), RouteProvider()).plan(command))

    selected_pairs = [
        {activity.provider_poi_id for activity in day.activities}
        for day in result.itinerary.days
    ]
    assert selected_pairs == [{"a", "c"}, {"b", "d"}]


def test_failed_route_combinations_are_bounded_per_plan() -> None:
    payload = _v2_command()
    payload["payload"]["trip"]["endDate"] = "2026-08-07"
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["arrival"] = None
    constraints["departure"] = None
    constraints["accommodation"] = None
    constraints["mustVisitPlaces"] = []
    constraints["avoidPlaces"] = []
    constraints["mealWindows"] = []
    constraints["mobilityLevel"] = "REDUCED"
    constraints["preferences"] = []
    payload["payload"]["guideEvidence"]["facts"] = []
    command = PlanningCreateCommand.model_validate(payload)
    candidates = tuple(_poi(f"poi-{index}", f"POI {index:02d}") for index in range(14))

    class MapProvider:
        async def search_pois(self, request: object):
            del request
            return ProviderSuccess(
                data=candidates,
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 7, 14, tzinfo=UTC),
                estimated=False,
            )

    class RouteProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def get_route(self, request: object):
            self.calls += 1
            return _route_success(request, distance=5_000)

    routes = RouteProvider()
    with pytest.raises(PlanningProviderError, match="PAIR_ATTEMPT_BUDGET_EXHAUSTED"):
        asyncio.run(AmapPlanningProvider(MapProvider(), routes).plan(command))

    assert routes.calls <= 96


def test_queue_delay_removes_guide_fact_that_expired_before_execution() -> None:
    payload = _v2_command()
    payload["payload"]["trip"]["constraints"]["mustVisitPlaces"] = []
    command = PlanningCreateCommand.model_validate(payload)
    received_fact_counts: list[int] = []

    class CapturingProvider:
        async def plan(self, received: PlanningCreateCommand) -> PlanningResult:
            received_fact_counts.append(len(received.payload.guide_evidence.facts))
            return await DemoPlanningProvider().plan(received)

    completed = asyncio.run(
        process_planning_create(
            command,
            CapturingProvider(),
            occurred_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
    )

    assert received_fact_counts == [0]
    assert completed.payload.knowledge.status == "DEMO"


def test_used_guide_citation_survives_twenty_rag_citations() -> None:
    payload = _v2_command()
    payload["payload"]["trip"]["constraints"]["mustVisitPlaces"] = []
    command = PlanningCreateCommand.model_validate(payload)
    fact_id = command.payload.guide_evidence.facts[0].fact_id
    rag_citations = tuple(
        KnowledgeCitationSnapshot(
            document_id=f"doc-{index}",
            document_version=1,
            chunk_id=f"chunk-{index}",
            chunk_index=index,
            title=f"RAG {index}",
            source_url=f"https://example.com/rag/{index}",
            source_name="example.com",
            collected_at=datetime(2026, 7, 13, tzinfo=UTC),
            reliability_level="official",
            similarity=0.9,
        )
        for index in range(20)
    )

    class GuideAwareProvider:
        async def plan(self, received: PlanningCreateCommand) -> PlanningResult:
            base = await DemoPlanningProvider().plan(received)
            return PlanningResult(
                provider=base.provider,
                itinerary=base.itinerary,
                guide_fact_ids=(fact_id,),
            )

    class SaturatedKnowledgeProvider:
        async def get_evidence(self, received: PlanningCreateCommand) -> KnowledgeEvidence:
            del received
            return KnowledgeEvidence(
                status="REAL",
                query="Guangzhou evidence",
                citations=rag_citations,
                freshness=KnowledgeFreshness(
                    status="FRESH",
                    checked_at=datetime(2026, 7, 14, tzinfo=UTC),
                ),
            )

    completed = asyncio.run(
        process_planning_create(
            command,
            GuideAwareProvider(),
            knowledge_provider=SaturatedKnowledgeProvider(),
            occurred_at=datetime(2026, 7, 14, 4, tzinfo=UTC),
        )
    )

    assert len(completed.payload.knowledge.citations) == 20
    assert str(fact_id) in {
        citation.chunk_id for citation in completed.payload.knowledge.citations
    }
