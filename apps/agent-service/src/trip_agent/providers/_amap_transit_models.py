"""AMap v3 integrated transit-route response models.

These models mirror the REAL v3/direction/transit/integrated response shape
(verified against live AMap data on 2026-08-19):

- ``transits[]`` → each transit alternative has cost/duration/distance/
  walking_distance/nightflag and ``segments[]`` (NOT ``steps``).
- each segment has ``walking`` {origin, destination, distance, duration,
  steps[]} and ``bus`` {buslines[]}; ``buslines`` may be empty.
- walking segments carry their polyline inside ``walking.steps[].polyline``
  (there is no top-level walking polyline).
- bus lines carry ``name``/``type``/``distance``/``duration``/``polyline``.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trip_agent.providers._route_contracts import RoutePlan


class _AmapBusline(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    type: str = ""
    distance: str = "0"
    duration: str = "0"
    polyline: str = ""


class _AmapWalkingStep(BaseModel):
    model_config = ConfigDict(extra="ignore")
    instruction: str = "步行"
    distance: str = "0"
    polyline: str = ""


class _AmapSegmentWalking(BaseModel):
    model_config = ConfigDict(extra="ignore")
    distance: str
    duration: str
    steps: tuple[_AmapWalkingStep, ...] = Field(default=())


class _AmapSegmentBus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    buslines: tuple[_AmapBusline, ...] = Field(default=())


class _AmapTransitSegment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    walking: _AmapSegmentWalking | None = None
    bus: _AmapSegmentBus | None = None

    @field_validator("walking", "bus", mode="before")
    @classmethod
    def _empty_segment_array_to_none(cls, value: object) -> object:
        # Real AMap emits walking/bus as an object when present and as an
        # empty array when absent — treat [] as no segment.  A NON-empty
        # array is malformed and must fail validation (→ PROVIDER_SCHEMA_CHANGED
        # upstream), never be silently treated as "no segment".
        if isinstance(value, list):
            if len(value) == 0:
                return None
            return value
        return value


class _AmapTransitPath(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cost: str | None = None
    duration: str
    walking_distance: str | None = None
    distance: str
    segments: tuple[_AmapTransitSegment, ...] = Field(min_length=1)


class _AmapTransitRoute(BaseModel):
    model_config = ConfigDict(extra="ignore")
    transits: tuple[_AmapTransitPath, ...]


class AmapTransitResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
    info: str
    infocode: str
    count: str | None = None
    route: _AmapTransitRoute | None = None


class CachedTransitRoute(BaseModel):
    data: RoutePlan
    fetched_at: datetime
