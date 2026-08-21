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

type RouteMode = Literal["WALKING", "DRIVING", "TRANSIT"]
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
    city: str | None = None
    destination_city: str | None = None
    strategy: int = Field(default=0, ge=0)
    nightflag: Literal[0, 1] = 0

    @model_validator(mode="after")
    def require_timezone(self) -> Self:
        if self.departure_at.utcoffset() is None:
            raise ValueError("route departure_at must include a timezone")
        return self

    @model_validator(mode="after")
    def require_city_for_transit(self) -> Self:
        if self.mode == "TRANSIT" and self.city is None:
            raise ValueError("transit route requests require a city")
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
    estimated_cost: float | None = Field(default=None, ge=0)
    walking_distance_meters: int | None = Field(default=None, ge=0)
    transfer_count: int | None = Field(default=None, ge=0)


type RouteResult = ProviderSuccess[RoutePlan] | ProviderFailure


class RouteProvider(Protocol):
    async def get_route(self, request: RouteRequest) -> RouteResult: ...
