"""Strongly typed contracts shared by route provider adapters."""

from datetime import datetime
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, StringConstraints, model_validator

from trip_agent.providers.map import (
    Coordinates,
    ProviderFailure,
    ProviderModel,
    ProviderPoiId,
    ProviderSuccess,
)

type RouteMode = Literal["WALKING"]
type RouteInstruction = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
]
MAX_ROUTE_DISTANCE_METERS = 40_100_000
MAX_ROUTE_DURATION_SECONDS = 31_536_000


class RouteRequest(ProviderModel):
    origin: Coordinates
    destination: Coordinates
    mode: RouteMode = "WALKING"
    departure_at: datetime
    origin_poi_id: ProviderPoiId | None = None
    destination_poi_id: ProviderPoiId | None = None

    @model_validator(mode="after")
    def require_timezone(self) -> Self:
        if self.departure_at.utcoffset() is None:
            raise ValueError("route departure_at must include a timezone")
        return self


class RouteStep(ProviderModel):
    instruction: RouteInstruction
    distance_meters: int = Field(strict=True, ge=0, le=MAX_ROUTE_DISTANCE_METERS)
    duration_seconds: int = Field(strict=True, ge=0, le=MAX_ROUTE_DURATION_SECONDS)
    polyline: tuple[Coordinates, ...] = Field(min_length=1, max_length=5_000)


class RoutePlan(ProviderModel):
    mode: RouteMode
    distance_meters: int = Field(strict=True, ge=0, le=MAX_ROUTE_DISTANCE_METERS)
    duration_seconds: int = Field(strict=True, ge=0, le=MAX_ROUTE_DURATION_SECONDS)
    steps: tuple[RouteStep, ...] = Field(min_length=1, max_length=1_000)
    polyline: tuple[Coordinates, ...] = Field(min_length=1, max_length=5_000)


type RouteResult = ProviderSuccess[RoutePlan] | ProviderFailure


class RouteProvider(Protocol):
    async def get_route(self, request: RouteRequest) -> RouteResult: ...
