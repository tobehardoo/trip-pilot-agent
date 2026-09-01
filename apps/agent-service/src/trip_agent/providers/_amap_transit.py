"""AMap v3 integrated transit-route infrastructure adapter."""

import hashlib
import json
import logging
from datetime import UTC, datetime
from time import perf_counter
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from trip_agent.providers._amap_transit_failures import AmapTransitFailures
from trip_agent.providers._amap_transit_models import (
    AmapTransitResponse,
    CachedTransitRoute,
    _AmapTransitPath,
    _AmapWalkingStep,
)
from trip_agent.providers._route_contracts import (
    RoutePlan,
    RouteRequest,
    RouteResult,
    RouteStep,
)
from trip_agent.providers.errors import ProviderErrorCategory
from trip_agent.providers.map import (
    Coordinates,
    JsonCache,
    ProviderFailure,
    ProviderSuccess,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AmapTransitProvider",
    "Coordinates",
    "ProviderFailure",
    "ProviderSuccess",
    "RouteRequest",
]


class AmapTransitProvider:
    """AMap v3 integrated transit adapter with an optional JSON cache."""

    endpoint = "https://restapi.amap.com/v3/direction/transit/integrated"

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient,
        cache: JsonCache | None = None,
        cache_ttl_seconds: int = 3_600,
    ) -> None:
        if not api_key.strip():
            raise ValueError("AMap API key cannot be empty")
        if cache_ttl_seconds <= 0:
            raise ValueError("cache TTL must be positive")
        self._api_key = api_key.strip()
        self._http_client = http_client
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds

    async def get_route(self, request: RouteRequest) -> RouteResult:
        started_at = perf_counter()
        cache_key = self._cache_key(request)
        cached = await self._read_cache(cache_key)
        if cached is not None:
            return ProviderSuccess(
                data=cached.data,
                provider="AMAP",
                latency_ms=AmapTransitFailures.elapsed_ms(started_at),
                cached=True,
                fetched_at=cached.fetched_at,
                estimated=False,
            )

        try:
            response = await self._http_client.get(
                self.endpoint,
                params=self._request_params(request),
            )
        except httpx.TimeoutException as exception:
            return AmapTransitFailures.create(
                "PROVIDER_TIMEOUT",
                "AMap transit request timed out",
                retryable=True,
                started_at=started_at,
                cause_type=type(exception).__name__,
            )
        except httpx.RequestError as exception:
            return AmapTransitFailures.create(
                "PROVIDER_UNAVAILABLE",
                "AMap transit service is temporarily unavailable",
                category=ProviderErrorCategory.NETWORK_ERROR,
                retryable=True,
                started_at=started_at,
                cause_type=type(exception).__name__,
            )

        if response.status_code >= 400:
            return AmapTransitFailures.from_http(
                response.status_code,
                started_at,
                retry_after_seconds=self._retry_after_seconds(response),
            )

        try:
            payload = AmapTransitResponse.model_validate(response.json())
        except (ValidationError, ValueError, TypeError):
            return AmapTransitFailures.create(
                "PROVIDER_SCHEMA_CHANGED",
                "AMap returned an unexpected transit response",
                retryable=True,
                started_at=started_at,
            )

        if payload.status != "1" or payload.infocode != "10000":
            return AmapTransitFailures.from_business(payload.infocode, started_at)
        if payload.route is None:
            return AmapTransitFailures.create(
                "PROVIDER_SCHEMA_CHANGED",
                "AMap transit response is missing route data",
                retryable=True,
                started_at=started_at,
            )
        if not payload.route.transits:
            return AmapTransitFailures.create(
                "ROUTE_NOT_FOUND",
                "No matching transit route was found",
                retryable=False,
                started_at=started_at,
            )
        try:
            plan = self._to_plan(
                payload.route.transits[0],
                request.origin,
                request.destination,
            )
        except (ValidationError, ValueError, TypeError):
            return AmapTransitFailures.create(
                "PROVIDER_SCHEMA_CHANGED",
                "AMap returned an unexpected transit route structure",
                retryable=True,
                started_at=started_at,
            )

        fetched_at = datetime.now(UTC)
        result = ProviderSuccess(
            data=plan,
            provider="AMAP",
            latency_ms=AmapTransitFailures.elapsed_ms(started_at),
            cached=False,
            fetched_at=fetched_at,
            estimated=False,
        )
        await self._write_cache(cache_key, CachedTransitRoute(data=plan, fetched_at=fetched_at))
        return result

    async def _read_cache(self, cache_key: str) -> CachedTransitRoute | None:
        if self._cache is None:
            return None
        try:
            cached_value = await self._cache.get(cache_key)
            if cached_value is None:
                return None
            return CachedTransitRoute.model_validate_json(cached_value)
        except Exception:
            logger.warning("Ignoring unreadable transit cache entry", exc_info=True)
            return None

    async def _write_cache(self, cache_key: str, value: CachedTransitRoute) -> None:
        if self._cache is None:
            return
        try:
            await self._cache.set(
                cache_key,
                value.model_dump_json(),
                ttl_seconds=self._cache_ttl_seconds,
            )
        except Exception:
            logger.warning("Transit cache write failed", exc_info=True)

    def _request_params(self, request: RouteRequest) -> dict[str, str]:
        if request.city is None:
            raise ValueError("transit route requests require a city")
        departure = request.departure_at.astimezone(ZoneInfo("Asia/Shanghai"))
        return {
            "key": self._api_key,
            "origin": self._coordinate_pair(request.origin),
            "destination": self._coordinate_pair(request.destination),
            "city": request.city,
            "strategy": str(request.strategy),
            "nightflag": str(request.nightflag),
            "date": departure.strftime("%Y-%m-%d"),
            "time": departure.strftime("%H:%M"),
            "extensions": "base",
            "output": "JSON",
        }

    @staticmethod
    def _to_plan(
        path: _AmapTransitPath,
        origin: Coordinates,
        destination: Coordinates,
    ) -> RoutePlan:
        steps: list[RouteStep] = []
        vehicle_segments = 0
        fallback_walking_meters = 0
        for segment in path.segments:
            if segment.walking is not None:
                walking = segment.walking
                fallback_walking_meters += int(walking.distance)
                polyline = AmapTransitProvider._walking_polyline(walking.steps)
                if polyline:
                    steps.append(
                        RouteStep(
                            instruction="步行",
                            distance_meters=int(walking.distance),
                            duration_seconds=int(walking.duration),
                            polyline=polyline,
                        )
                    )
            buslines = segment.bus.buslines if segment.bus is not None else ()
            if buslines:
                line = buslines[0]
                vehicle_segments += 1
                polyline = AmapTransitProvider._parse_polyline(line.polyline)
                if polyline:
                    steps.append(
                        RouteStep(
                            instruction=f"乘坐{line.name}",
                            distance_meters=int(line.distance),
                            duration_seconds=int(line.duration),
                            polyline=polyline,
                        )
                    )
            # taxi-only / railway-only segments without walking or bus lines
            # are not routeable facts for the flat leg — skip them.
        if not steps:
            endpoint_polyline = (origin, destination)
            steps.append(
                RouteStep(
                    instruction="公共交通",
                    distance_meters=int(path.distance),
                    duration_seconds=int(path.duration),
                    polyline=endpoint_polyline,
                )
            )
        polyline: list[Coordinates] = []
        for step in steps:
            for point in step.polyline:
                if not polyline or point != polyline[-1]:
                    polyline.append(point)
        if path.walking_distance is not None:
            walking_distance_meters = int(path.walking_distance)
        elif fallback_walking_meters > 0:
            walking_distance_meters = fallback_walking_meters
        else:
            walking_distance_meters = None
        # Provider actual cost is the source of truth.  Missing/empty cost is
        # unknown (None) — never 0, which means free.  A malformed cost value
        # raises and the caller maps it to PROVIDER_SCHEMA_CHANGED, matching
        # the existing driving/walking route provider policy.
        estimated_cost: float | None = None
        if path.cost is not None and path.cost.strip():
            estimated_cost = float(path.cost)
        return RoutePlan(
            mode="TRANSIT",
            distance_meters=int(path.distance),
            duration_seconds=int(path.duration),
            steps=tuple(steps),
            polyline=tuple(polyline),
            estimated_cost=estimated_cost,
            walking_distance_meters=walking_distance_meters,
            transfer_count=max(0, vehicle_segments - 1),
        )

    @staticmethod
    def _walking_polyline(steps: tuple[_AmapWalkingStep, ...]) -> tuple[Coordinates, ...]:
        """Walking segments carry their geometry inside each step's polyline."""
        points: list[Coordinates] = []
        for step in steps:
            for point in AmapTransitProvider._parse_polyline(step.polyline):
                if not points or point != points[-1]:
                    points.append(point)
        return tuple(points)

    @staticmethod
    def _parse_polyline(value: str) -> tuple[Coordinates, ...]:
        if not value.strip():
            return ()
        points = []
        for raw_point in value.split(";"):
            longitude_text, latitude_text = raw_point.split(",", maxsplit=1)
            points.append(
                Coordinates(
                    longitude=float(longitude_text),
                    latitude=float(latitude_text),
                )
            )
        return tuple(points)

    @staticmethod
    def _coordinate_pair(value: Coordinates) -> str:
        return f"{value.longitude:.6f},{value.latitude:.6f}"

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return max(0, float(value))
        except ValueError:
            return None

    @staticmethod
    def _cache_key(request: RouteRequest) -> str:
        departure = request.departure_at.astimezone(UTC)
        departure_bucket = departure.replace(
            minute=(departure.minute // 15) * 15,
            second=0,
            microsecond=0,
        )
        source = json.dumps(
            {
                "origin": AmapTransitProvider._coordinate_pair(request.origin),
                "destination": AmapTransitProvider._coordinate_pair(request.destination),
                "origin_poi_id": request.origin_poi_id,
                "destination_poi_id": request.destination_poi_id,
                "city": request.city,
                "strategy": request.strategy,
                "nightflag": request.nightflag,
                "departure": departure_bucket.isoformat(),
                "provider": "AMAP",
                "data_version": 1,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return f"map:transit:v1:{hashlib.sha256(source).hexdigest()}"
