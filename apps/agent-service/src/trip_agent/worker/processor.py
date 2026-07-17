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
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    PlanningCompletedEvent,
    PlanningCompletedPayload,
    PlanningCreateCommand,
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
        )


class AmapPlanningProvider:
    def __init__(self, map_provider: MapProvider) -> None:
        self._map_provider = map_provider

    async def plan(self, command: PlanningCreateCommand) -> PlanningResult:
        trip = command.payload.trip
        day_count = (trip.end_date - trip.start_date).days + 1
        pois = await self._collect_pois(command, day_count)
        if len(pois) < day_count:
            raise PlanningProviderError("INSUFFICIENT_AMAP_POIS")
        days = tuple(
            self._day(command, offset, poi)
            for offset, poi in enumerate(pois[:day_count])
        )
        return PlanningResult(
            provider="AMAP",
            itinerary=Itinerary(
                title=f"{trip.destination} 真实地点行程",
                days=days,
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

    def _day(self, command: PlanningCreateCommand, offset: int, poi: Poi) -> ItineraryDay:
        trip_date = command.payload.trip.start_date + timedelta(days=offset)
        start_time = datetime.combine(trip_date, time(hour=9), tzinfo=CHINA_TIME_ZONE)
        return ItineraryDay(
            date=trip_date,
            activities=(
                ItineraryActivity(
                    title=poi.name,
                    start_time=start_time,
                    end_time=start_time + timedelta(hours=2),
                    estimated_cost=Decimal("0"),
                    source="AMAP",
                    provider_poi_id=poi.provider_id,
                    coordinates=ActivityCoordinates(
                        longitude=_coordinate_decimal(poi.coordinates.longitude),
                        latitude=_coordinate_decimal(poi.coordinates.latitude),
                    ),
                    address=poi.address,
                ),
            ),
        )


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
        schema_version=2,
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


def _candidate_keywords(preferences: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*preferences, *DEFAULT_POI_KEYWORDS)))[:MAX_POI_QUERIES]
