"""Deterministic route estimates for offline development."""

from datetime import UTC, datetime
from math import asin, ceil, cos, radians, sin, sqrt
from time import perf_counter

from trip_agent.providers._route_contracts import (
    RoutePlan,
    RouteRequest,
    RouteResult,
    RouteStep,
)
from trip_agent.providers.errors import ProviderOperation, category_for_error_code
from trip_agent.providers.map import (
    Coordinates,
    ProviderFailure,
    ProviderSuccess,
)


class DemoRouteProvider:
    """Create a deterministic straight-line walking estimate."""

    _earth_radius_meters = 6_371_000
    _speed_meters_per_second = {
        "WALKING": 1.25,
        "DRIVING": 8.33,
    }

    async def get_route(self, request: RouteRequest) -> RouteResult:
        started_at = perf_counter()
        if request.mode == "TRANSIT":
            return ProviderFailure(
                provider="DEMO",
                error_code="PROVIDER_UNSUPPORTED_MODE",
                error_message="Demo does not support transit routes",
                category=category_for_error_code("PROVIDER_UNSUPPORTED_MODE"),
                operation=ProviderOperation.ROUTE,
                retryable=False,
                latency_ms=self._elapsed_ms(started_at),
                fetched_at=datetime.now(UTC),
            )
        distance = self._distance_meters(request.origin, request.destination)
        duration = ceil(distance / self._speed_meters_per_second[request.mode])
        polyline = (request.origin, request.destination)
        plan = RoutePlan(
            mode=request.mode,
            distance_meters=distance,
            duration_seconds=duration,
            steps=(
                RouteStep(
                    instruction="Demo estimated walking route",
                    distance_meters=distance,
                    duration_seconds=duration,
                    polyline=polyline,
                ),
            ),
            polyline=polyline,
            estimated_cost=0.0 if request.mode == "WALKING" else None,
        )
        return ProviderSuccess(
            data=plan,
            provider="DEMO",
            latency_ms=self._elapsed_ms(started_at),
            cached=False,
            fetched_at=datetime.now(UTC),
            estimated=True,
        )

    @classmethod
    def _distance_meters(cls, origin: Coordinates, destination: Coordinates) -> int:
        latitude_delta = radians(destination.latitude - origin.latitude)
        longitude_delta = radians(destination.longitude - origin.longitude)
        origin_latitude = radians(origin.latitude)
        destination_latitude = radians(destination.latitude)
        haversine = sin(latitude_delta / 2) ** 2 + (
            cos(origin_latitude)
            * cos(destination_latitude)
            * sin(longitude_delta / 2) ** 2
        )
        angular_distance = 2 * asin(min(1.0, sqrt(haversine)))
        return round(cls._earth_radius_meters * angular_distance)

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))
