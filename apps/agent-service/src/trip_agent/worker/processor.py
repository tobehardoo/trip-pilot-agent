"""Pure planning command processing."""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from trip_agent.planning.candidates import CandidateRanker
from trip_agent.planning.optimization import (
    DailyOptimizationRequest,
    DailyOptimizer,
    OptimizationConflict,
    RelaxationSuggestion,
    TimeBlock,
)
from trip_agent.providers.map import (
    MapProvider,
    MapProviderName,
    Poi,
    PoiSearchRequest,
    ProviderFailure,
)
from trip_agent.providers.route import DemoRouteProvider, RouteProvider, RouteRequest
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    KnowledgeEvidence,
    KnowledgeFreshness,
    PlanningCompletedEvent,
    PlanningCompletedPayload,
    PlanningConflict,
    PlanningCreateCommand,
    PlanningFailedEvent,
    PlanningFailedPayload,
    PlanningRelaxation,
    TransitLeg,
)
from trip_agent.worker.knowledge import build_knowledge_query

CHINA_TIME_ZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
COORDINATE_SCALE = Decimal("0.0000001")
DEFAULT_POI_KEYWORDS = ("景点", "博物馆", "公园", "美食")
MAX_POI_QUERIES = 6
AMAP_ACTIVITY_ESTIMATED_COST = Decimal("100.00")


class PlanningProvider(Protocol):
    async def plan(self, command: PlanningCreateCommand) -> "PlanningResult": ...


class KnowledgeEvidenceProvider(Protocol):
    async def get_evidence(self, command: PlanningCreateCommand) -> KnowledgeEvidence: ...


@dataclass(frozen=True)
class PlanningResult:
    provider: MapProviderName
    itinerary: Itinerary


class PlanningProviderError(Exception):
    """An expected provider failure that may use the configured fallback."""


class PlanningInfeasibleError(Exception):
    """Hard constraints cannot be satisfied and must be shown to the user."""

    def __init__(
        self,
        conflicts: tuple[OptimizationConflict, ...],
        relaxations: tuple[RelaxationSuggestion, ...],
    ) -> None:
        super().__init__(conflicts[0].message if conflicts else "No feasible itinerary")
        self.conflicts = conflicts
        self.relaxations = relaxations


class DemoPlanningProvider:
    async def plan(self, command: PlanningCreateCommand) -> PlanningResult:
        trip = command.payload.trip
        day_count = (trip.end_date - trip.start_date).days + 1
        days = tuple(self._day(command, offset) for offset in range(day_count))
        return PlanningResult(
            provider="DEMO",
            itinerary=Itinerary(
                title=f"{trip.destination} Demo 行程",
                days=days,
                estimated_total_cost=Decimal("0"),
            ),
        )

    def _day(self, command: PlanningCreateCommand, offset: int) -> ItineraryDay:
        trip_date = command.payload.trip.start_date + timedelta(days=offset)
        start_time = datetime.combine(trip_date, time(hour=9), tzinfo=CHINA_TIME_ZONE)
        return ItineraryDay(
            date=trip_date,
            activities=(
                ItineraryActivity(
                    title=f"{command.payload.trip.destination} Demo 探索",
                    start_time=start_time,
                    end_time=start_time + timedelta(hours=2),
                    estimated_cost=Decimal("0"),
                    source="DEMO",
                ),
            ),
            transit_legs=(),
        )


class DemoKnowledgeEvidenceProvider:
    async def get_evidence(self, command: PlanningCreateCommand) -> KnowledgeEvidence:
        return KnowledgeEvidence(
            status="DEMO",
            query=build_knowledge_query(command),
            citations=(),
            freshness=KnowledgeFreshness(status="UNAVAILABLE"),
            message="演示模式未使用生产知识检索",
        )


class AmapPlanningProvider:
    def __init__(
        self,
        map_provider: MapProvider,
        route_provider: RouteProvider,
        route_fallback: RouteProvider | None = None,
        candidate_ranker: CandidateRanker | None = None,
        optimizer: DailyOptimizer | None = None,
    ) -> None:
        self._map_provider = map_provider
        self._route_provider = route_provider
        self._route_fallback = route_fallback or DemoRouteProvider()
        self._candidate_ranker = candidate_ranker or CandidateRanker()
        self._optimizer = optimizer or DailyOptimizer()

    async def plan(self, command: PlanningCreateCommand) -> PlanningResult:
        trip = command.payload.trip
        day_count = (trip.end_date - trip.start_date).days + 1
        required_pois = day_count * 2
        raw_pois = await self._collect_pois(command, required_pois)
        ranking = self._candidate_ranker.rank(
            raw_pois,
            destination=trip.destination,
            preferences=trip.constraints.preferences,
            traveler_type=trip.constraints.traveler_type,
            limit=required_pois,
        )
        pois = tuple(item.poi for item in ranking.selected)
        if len(pois) < required_pois:
            raise PlanningProviderError("INSUFFICIENT_AMAP_POIS")
        estimated_total_cost = AMAP_ACTIVITY_ESTIMATED_COST * required_pois
        budget = trip.constraints.budget_amount
        if budget is not None and estimated_total_cost > budget:
            raise PlanningInfeasibleError(
                conflicts=(OptimizationConflict(
                    "BUDGET_EXCEEDED",
                    f"预计活动费用 {estimated_total_cost:.2f} 超出预算 {budget:.2f}",
                    ("budgetAmount",),
                ),),
                relaxations=(
                    RelaxationSuggestion("INCREASE_BUDGET", "提高预算上限"),
                    RelaxationSuggestion("REDUCE_OPTIONAL_ACTIVITIES", "减少可选活动"),
                ),
            )
        days = []
        for offset in range(day_count):
            first_index = offset * 2
            days.append(
                await self._day(
                    command,
                    offset,
                    pois[first_index],
                    pois[first_index + 1],
                )
            )
        return PlanningResult(
            provider="AMAP",
            itinerary=Itinerary(
                title=f"{trip.destination} 真实地点行程",
                days=tuple(days),
                estimated_total_cost=estimated_total_cost,
            ),
        )

    async def _collect_pois(
        self, command: PlanningCreateCommand, required_count: int
    ) -> tuple[Poi, ...]:
        trip = command.payload.trip
        candidates: list[Poi] = []
        keywords = _candidate_keywords(trip.constraints.preferences)
        required_preference_queries = max(
            1,
            min(
                len(tuple(dict.fromkeys(
                    item.strip() for item in trip.constraints.preferences if item.strip()
                ))),
                len(keywords),
            ),
        )
        for query_index, keyword in enumerate(keywords, start=1):
            search = await self._map_provider.search_pois(
                PoiSearchRequest(
                    city=trip.destination,
                    keyword=keyword,
                    limit=min(required_count * 3, 25),
                )
            )
            if isinstance(search, ProviderFailure):
                if search.error_code == "POI_NOT_FOUND":
                    continue
                raise PlanningProviderError(search.error_code)
            if search.provider != "AMAP":
                raise PlanningProviderError("UNEXPECTED_MAP_PROVIDER")
            candidates.extend(search.data)
            if query_index < required_preference_queries:
                continue
            ranking = self._candidate_ranker.rank(
                tuple(candidates),
                destination=trip.destination,
                preferences=trip.constraints.preferences,
                traveler_type=trip.constraints.traveler_type,
                limit=required_count,
            )
            if len(ranking.selected) >= required_count:
                return tuple(candidates)
        return tuple(candidates)

    async def _day(
        self,
        command: PlanningCreateCommand,
        offset: int,
        first_poi: Poi,
        second_poi: Poi,
    ) -> ItineraryDay:
        trip_date = command.payload.trip.start_date + timedelta(days=offset)
        provisional_first_end = datetime.combine(
            trip_date, time(hour=11), tzinfo=CHINA_TIME_ZONE
        )
        route = await self._route(
            RouteRequest(
                origin=first_poi.coordinates,
                destination=second_poi.coordinates,
                departure_at=provisional_first_end,
                origin_poi_id=first_poi.provider_id,
                destination_poi_id=second_poi.provider_id,
            )
        )
        optimization = self._optimizer.optimize(
            DailyOptimizationRequest(
                date=trip_date,
                route_duration_seconds=route.data.duration_seconds,
                fixed_schedules=tuple(
                    TimeBlock(schedule.place_name, schedule.start_time, schedule.end_time)
                    for schedule in command.payload.trip.constraints.fixed_schedules
                ),
            )
        )
        if optimization.status == "INFEASIBLE":
            raise PlanningInfeasibleError(optimization.conflicts, optimization.relaxations)
        if any(
            value is None
            for value in (
                optimization.first_start,
                optimization.first_end,
                optimization.second_start,
                optimization.second_end,
            )
        ):
            raise RuntimeError("feasible optimizer result omitted schedule timestamps")
        first_start = optimization.first_start
        first_end = optimization.first_end
        second_start = optimization.second_start
        second_end = optimization.second_end
        assert first_start is not None
        assert first_end is not None
        assert second_start is not None
        assert second_end is not None
        return ItineraryDay(
            date=trip_date,
            activities=(
                _amap_activity(first_poi, first_start, first_end),
                _amap_activity(second_poi, second_start, second_end),
            ),
            transit_legs=(
                TransitLeg(
                    from_activity_index=0,
                    to_activity_index=1,
                    mode=route.data.mode,
                    distance_meters=route.data.distance_meters,
                    duration_seconds=route.data.duration_seconds,
                    provider=route.provider,
                    estimated=route.estimated,
                    polyline=tuple(
                        ActivityCoordinates(
                            longitude=_coordinate_decimal(point.longitude),
                            latitude=_coordinate_decimal(point.latitude),
                        )
                        for point in route.data.polyline
                    ),
                ),
            ),
        )

    async def _route(self, request: RouteRequest):
        result = await self._route_provider.get_route(request)
        if isinstance(result, ProviderFailure):
            result = await self._route_fallback.get_route(request)
        if isinstance(result, ProviderFailure):
            raise PlanningProviderError(result.error_code)
        if result.provider not in {"AMAP", "DEMO"}:
            raise PlanningProviderError("UNEXPECTED_ROUTE_PROVIDER")
        if (result.provider == "AMAP" and result.estimated) or (
            result.provider == "DEMO" and not result.estimated
        ):
            raise RuntimeError("route provider returned inconsistent source metadata")
        return result


class FallbackPlanningProvider:
    def __init__(self, primary: PlanningProvider, fallback: PlanningProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    async def plan(self, command: PlanningCreateCommand) -> PlanningResult:
        try:
            return await self._primary.plan(command)
        except PlanningProviderError:
            return await self._fallback.plan(command)


async def process_planning_create(
    command: PlanningCreateCommand,
    provider: PlanningProvider,
    *,
    knowledge_provider: KnowledgeEvidenceProvider | None = None,
    occurred_at: datetime | None = None,
) -> PlanningCompletedEvent:
    result = await provider.plan(command)
    knowledge = await (knowledge_provider or DemoKnowledgeEvidenceProvider()).get_evidence(command)
    return PlanningCompletedEvent(
        event_type="PLANNING_COMPLETED",
        schema_version=4,
        event_id=_completed_event_id(command.event_id),
        trace_id=command.trace_id,
        task_id=command.task_id,
        trip_id=command.trip_id,
        run_id=_run_id(command.task_id),
        occurred_at=occurred_at or datetime.now(UTC),
        payload=PlanningCompletedPayload(
            provider=result.provider,
            itinerary=result.itinerary,
            knowledge=knowledge,
        ),
    )


def planning_failed_event(
    command: PlanningCreateCommand,
    failure: PlanningInfeasibleError,
    *,
    occurred_at: datetime | None = None,
) -> PlanningFailedEvent:
    return PlanningFailedEvent(
        event_type="PLANNING_FAILED",
        schema_version=1,
        event_id=_failed_event_id(command.event_id),
        trace_id=command.trace_id,
        task_id=command.task_id,
        trip_id=command.trip_id,
        run_id=_run_id(command.task_id),
        occurred_at=occurred_at or datetime.now(UTC),
        payload=PlanningFailedPayload(
            status="FAILED",
            error_code="NO_FEASIBLE_ITINERARY",
            message=str(failure),
            conflicts=tuple(
                PlanningConflict(
                    code=item.code,
                    message=item.message,
                    affected=item.affected,
                )
                for item in failure.conflicts
            ),
            relaxation_suggestions=tuple(
                PlanningRelaxation(code=item.code, message=item.message)
                for item in failure.relaxations
            ),
        ),
    )


def _completed_event_id(command_event_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"trip-pilot/planning-completed/{command_event_id}")


def _failed_event_id(command_event_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"trip-pilot/planning-failed/{command_event_id}")


def _run_id(task_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"trip-pilot/agent-run/{task_id}")


def _coordinate_decimal(value: float) -> Decimal:
    return Decimal(str(value)).quantize(COORDINATE_SCALE)


def _amap_activity(poi: Poi, start_time: datetime, end_time: datetime) -> ItineraryActivity:
    return ItineraryActivity(
        title=poi.name,
        start_time=start_time,
        end_time=end_time,
        estimated_cost=AMAP_ACTIVITY_ESTIMATED_COST,
        source="AMAP",
        provider_poi_id=poi.provider_id,
        coordinates=ActivityCoordinates(
            longitude=_coordinate_decimal(poi.coordinates.longitude),
            latitude=_coordinate_decimal(poi.coordinates.latitude),
        ),
        address=poi.address,
    )


def _candidate_keywords(preferences: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*preferences, *DEFAULT_POI_KEYWORDS)))[:MAX_POI_QUERIES]
