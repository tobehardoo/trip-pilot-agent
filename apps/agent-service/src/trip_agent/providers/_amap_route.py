"""AMap v5 walking-route infrastructure adapter."""

import hashlib
import json
import logging
from datetime import UTC, datetime
from time import perf_counter

import httpx
from pydantic import ValidationError

from trip_agent.providers._amap_route_failures import AmapRouteFailures
from trip_agent.providers._amap_route_models import (
    AmapWalkingPath,
    AmapWalkingResponse,
    CachedRoute,
)
from trip_agent.providers._route_contracts import (
    RouteMode,
    RoutePlan,
    RouteRequest,
    RouteResult,
    RouteStep,
)
from trip_agent.providers.map import (
    Coordinates,
    JsonCache,
    ProviderSuccess,
)

logger = logging.getLogger(__name__)


class AmapRouteProvider:
    """AMap v5 walking-route adapter with an optional JSON cache."""

    endpoint = "https://restapi.amap.com/v5/direction/walking"
    driving_endpoint = "https://restapi.amap.com/v5/direction/driving"
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
                latency_ms=AmapRouteFailures.elapsed_ms(started_at),
                cached=True,
                fetched_at=cached.fetched_at,
                estimated=False,
            )

        try:
            response = await self._http_client.get(
                self.driving_endpoint if request.mode == "DRIVING" else self.endpoint,
                params=self._request_params(request),
            )
        except httpx.TimeoutException:
            return AmapRouteFailures.create(
                "PROVIDER_TIMEOUT",
                "AMap route request timed out",
                retryable=True,
                started_at=started_at,
            )
        except httpx.RequestError:
            return AmapRouteFailures.create(
                "PROVIDER_UNAVAILABLE",
                "AMap route service is temporarily unavailable",
                retryable=True,
                started_at=started_at,
            )

        if response.status_code >= 400:
            return AmapRouteFailures.from_http(response.status_code, started_at)

        try:
            payload = AmapWalkingResponse.model_validate(response.json())
        except (ValidationError, ValueError, TypeError):
            return AmapRouteFailures.create(
                "PROVIDER_SCHEMA_CHANGED",
                "AMap returned an unexpected route response",
                retryable=False,
                started_at=started_at,
            )

        if payload.status != "1" or payload.infocode != "10000":
            return AmapRouteFailures.from_business(payload.infocode, started_at)
        if payload.route is None:
            return AmapRouteFailures.create(
                "PROVIDER_SCHEMA_CHANGED",
                "AMap route response is missing route data",
                retryable=False,
                started_at=started_at,
            )
        if not payload.route.paths:
            return AmapRouteFailures.create(
                "ROUTE_NOT_FOUND",
                "No matching walking route was found",
                retryable=False,
                started_at=started_at,
            )
        try:
            plan = self._to_plan(payload.route.paths[0], request.mode)
        except (ValidationError, ValueError, TypeError):
            return AmapRouteFailures.create(
                "PROVIDER_SCHEMA_CHANGED",
                "AMap returned an unexpected walking route structure",
                retryable=False,
                started_at=started_at,
            )

        fetched_at = datetime.now(UTC)
        result = ProviderSuccess(
            data=plan,
            provider="AMAP",
            latency_ms=AmapRouteFailures.elapsed_ms(started_at),
            cached=False,
            fetched_at=fetched_at,
            estimated=False,
        )
        await self._write_cache(cache_key, CachedRoute(data=plan, fetched_at=fetched_at))
        return result

    async def _read_cache(self, cache_key: str) -> CachedRoute | None:
        if self._cache is None:
            return None
        try:
            cached_value = await self._cache.get(cache_key)
            if cached_value is None:
                return None
            return CachedRoute.model_validate_json(cached_value)
        except Exception:
            logger.warning("Ignoring unreadable route cache entry", exc_info=True)
            return None

    async def _write_cache(self, cache_key: str, value: CachedRoute) -> None:
        if self._cache is None:
            return
        try:
            await self._cache.set(
                cache_key,
                value.model_dump_json(),
                ttl_seconds=self._cache_ttl_seconds,
            )
        except Exception:
            logger.warning("Route cache write failed", exc_info=True)

    def _request_params(self, request: RouteRequest) -> dict[str, str]:
        params = {
            "key": self._api_key,
            "origin": self._coordinate_pair(request.origin),
            "destination": self._coordinate_pair(request.destination),
            "show_fields": "cost,navi,polyline",
            "output": "json",
        }
        if request.mode == "WALKING":
            params["isindoor"] = "0"
        else:
            params["strategy"] = "32"
        if request.origin_poi_id is not None:
            params["origin_id"] = request.origin_poi_id
        if request.destination_poi_id is not None:
            params["destination_id"] = request.destination_poi_id
        return params

    @staticmethod
    def _to_plan(path: AmapWalkingPath, mode: RouteMode = "WALKING") -> RoutePlan:
        steps = tuple(
            RouteStep(
                instruction=step.instruction,
                distance_meters=int(step.step_distance),
                duration_seconds=int(step.cost.duration),
                polyline=AmapRouteProvider._parse_polyline(step.polyline),
            )
            for step in path.steps
        )
        polyline: list[Coordinates] = []
        for step in steps:
            for point in step.polyline:
                if not polyline or point != polyline[-1]:
                    polyline.append(point)
        return RoutePlan(
            mode=mode,
            distance_meters=int(path.distance),
            duration_seconds=int(path.cost.duration),
            steps=steps,
            polyline=tuple(polyline),
        )

    @staticmethod
    def _parse_polyline(value: str) -> tuple[Coordinates, ...]:
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
    def _cache_key(request: RouteRequest) -> str:
        departure_hour = request.departure_at.astimezone(UTC).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        source = json.dumps(
            {
                "origin": AmapRouteProvider._coordinate_pair(request.origin),
                "destination": AmapRouteProvider._coordinate_pair(request.destination),
                "origin_poi_id": request.origin_poi_id,
                "destination_poi_id": request.destination_poi_id,
                "mode": request.mode,
                "departure_hour": departure_hour.isoformat(),
                "provider": "AMAP",
                "data_version": 1,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return f"map:route:v1:{hashlib.sha256(source).hexdigest()}"
