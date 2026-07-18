"""Pure planning command processing."""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

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
    PlanningCompletedEvent,
    PlanningCompletedPayload,
    PlanningCreateCommand,
    TransitLeg,
)

CHINA_TIME_ZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
COORDINATE_SCALE = Decimal("0.0000001")
DEFAULT_POI_KEYWORDS = ("景点", "博物馆", "公园", "美食")
MAX_POI_QUERIES = 6


class PlanningProvider(Protocol):
    async def plan(self, command: PlanningCreateCommand) -> "PlanningResult": ...


@dataclass(frozen=True)
class PlanningResult:
    provider: MapProviderName
    itinerary: Itinerary


class PlanningProviderError(Exception):
    """An expected provider failure that may use the configured fallback."""


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


class AmapPlanningProvider:
    def __init__(
        self,
        map_provider: MapProvider,
        route_provider: RouteProvider,
        route_fallback: RouteProvider | None = None,
    ) -> None:
        self._map_provider = map_provider
        self._route_provider = route_provider
        self._route_fallback = route_fallback or DemoRouteProvider()

    async def plan(self, command: PlanningCreateCommand) -> PlanningResult:
        trip = command.payload.trip
        day_count = (trip.end_date - trip.start_date).days + 1
        required_pois = day_count * 2
        pois = await self._collect_pois(command, required_pois)
        if len(pois) < required_pois:
            raise PlanningProviderError("INSUFFICIENT_AMAP_POIS")
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
                estimated_total_cost=Decimal("0"),
            ),
        )

    async def _collect_pois(
        self, command: PlanningCreateCommand, required_count: int
    ) -> tuple[Poi, ...]:
        trip = command.payload.trip
        candidates: list[Poi] = []
        seen_ids: set[str] = set()
        for keyword in _candidate_keywords(trip.constraints.preferences):
            search = await self._map_provider.search_pois(
                PoiSearchRequest(
                    city=trip.destination,
                    keyword=keyword,
                    limit=min(required_count, 25),
                )
            )
            if isinstance(search, ProviderFailure):
                if search.error_code == "POI_NOT_FOUND":
                    continue
                raise PlanningProviderError(search.error_code)
            if search.provider != "AMAP":
                raise PlanningProviderError("UNEXPECTED_MAP_PROVIDER")
            for poi in search.data:
                if poi.provider_id in seen_ids or not poi.address.strip():
                    continue
                candidates.append(poi)
                seen_ids.add(poi.provider_id)
                if len(candidates) == required_count:
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
        first_start = datetime.combine(trip_date, time(hour=9), tzinfo=CHINA_TIME_ZONE)
        first_end = first_start + timedelta(hours=2)
        route = await self._route(
            RouteRequest(
                origin=first_poi.coordinates,
                destination=second_poi.coordinates,
                departure_at=first_end,
                origin_poi_id=first_poi.provider_id,
                destination_poi_id=second_poi.provider_id,
            )
        )
        scheduled_second_start = datetime.combine(
            trip_date, time(hour=13), tzinfo=CHINA_TIME_ZONE
        )
        second_start = max(
            scheduled_second_start,
            first_end + timedelta(seconds=route.data.duration_seconds),
        )
        second_end = second_start + timedelta(hours=2)
        if second_end.date() != trip_date:
            raise PlanningProviderError("ROUTE_EXCEEDS_ITINERARY_DAY")
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
    occurred_at: datetime | None = None,
) -> PlanningCompletedEvent:
    result = await provider.plan(command)
    return PlanningCompletedEvent(
        event_type="PLANNING_COMPLETED",
        schema_version=3,
        event_id=_completed_event_id(command.event_id),
        trace_id=command.trace_id,
        task_id=command.task_id,
        trip_id=command.trip_id,
        run_id=_run_id(command.task_id),
        occurred_at=occurred_at or datetime.now(UTC),
        payload=PlanningCompletedPayload(
            provider=result.provider,
            itinerary=result.itinerary,
        ),
    )


def _completed_event_id(command_event_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"trip-pilot/planning-completed/{command_event_id}")


def _run_id(task_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"trip-pilot/agent-run/{task_id}")


def _coordinate_decimal(value: float) -> Decimal:
    return Decimal(str(value)).quantize(COORDINATE_SCALE)


def _amap_activity(poi: Poi, start_time: datetime, end_time: datetime) -> ItineraryActivity:
    return ItineraryActivity(
        title=poi.name,
        start_time=start_time,
        end_time=end_time,
        estimated_cost=Decimal("0"),
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
