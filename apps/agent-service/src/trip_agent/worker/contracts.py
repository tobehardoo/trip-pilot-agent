"""Typed message contracts for the planning worker."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

type JsonDecimal = Annotated[
    Decimal,
    Field(
        ge=Decimal("0"),
        le=Decimal("9999999999.99"),
        multiple_of=Decimal("0.01"),
    ),
    PlainSerializer(lambda value: float(value), return_type=float, when_used="json"),
]
type ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
]
type NameText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
type ItineraryText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
type ProviderPoiId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
type AddressText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
]
type JsonLongitude = Annotated[
    Decimal,
    Field(ge=Decimal("-180"), le=Decimal("180")),
    PlainSerializer(lambda value: float(value), return_type=float, when_used="json"),
]
type JsonLatitude = Annotated[
    Decimal,
    Field(ge=Decimal("-90"), le=Decimal("90")),
    PlainSerializer(lambda value: float(value), return_type=float, when_used="json"),
]


class MessageModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_alias=True,
        validate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class InboundMessageModel(MessageModel):
    model_config = ConfigDict(validate_by_alias=True, validate_by_name=False)


class FixedSchedule(InboundMessageModel):
    place_name: NameText
    start_time: datetime
    end_time: datetime

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.start_time.utcoffset() is None or self.end_time.utcoffset() is None:
            raise ValueError("fixed schedule startTime and endTime must include a timezone")
        if self.end_time <= self.start_time:
            raise ValueError("fixed schedule endTime must be after startTime")
        return self


class TripConstraints(InboundMessageModel):
    budget_amount: Decimal | None = Field(ge=0)
    travelers: int = Field(strict=True, ge=1, le=50)
    traveler_type: Literal["SOLO", "COUPLE", "FAMILY", "FRIENDS", "BUSINESS"]
    pace: Literal["RELAXED", "BALANCED", "INTENSIVE"]
    preferences: tuple[ShortText, ...] = Field(max_length=30)
    fixed_schedules: tuple[FixedSchedule, ...] = Field(max_length=30)
    schema_version: Literal[1]

    @field_validator("budget_amount", mode="before")
    @classmethod
    def validate_budget_type(cls, value: object) -> object:
        is_json_number = isinstance(value, int | float | Decimal) and not isinstance(value, bool)
        if value is not None and not is_json_number:
            raise ValueError("budgetAmount must be a JSON number or null")
        return value


class TripSnapshot(InboundMessageModel):
    title: NameText
    destination: NameText
    start_date: date
    end_date: date
    status: Literal["DRAFT"]
    version: int = Field(strict=True, ge=0)
    constraints: TripConstraints

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("trip endDate must not be before startDate")
        for schedule in self.constraints.fixed_schedules:
            starts_before_trip = schedule.start_time.date() < self.start_date
            ends_after_trip = schedule.end_time.date() > self.end_date
            if starts_before_trip or ends_after_trip:
                raise ValueError("fixed schedules must fall within trip dates")
        return self


class PlanningCreatePayload(InboundMessageModel):
    task_type: Literal["CREATE"]
    baseline_trip_version: int = Field(strict=True, ge=0)
    idempotency_key: UUID
    trip: TripSnapshot

    @model_validator(mode="after")
    def validate_baseline_version(self) -> Self:
        if self.baseline_trip_version != self.trip.version:
            raise ValueError("baselineTripVersion must match trip.version")
        return self


class PlanningCreateCommand(InboundMessageModel):
    event_type: Literal["PLANNING_CREATE_REQUESTED"]
    schema_version: Literal[1]
    event_id: UUID
    trace_id: UUID
    task_id: UUID
    trip_id: UUID
    occurred_at: datetime
    payload: PlanningCreatePayload

    @model_validator(mode="after")
    def validate_occurred_at(self) -> Self:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurredAt must include a timezone")
        return self


class ActivityCoordinates(MessageModel):
    longitude: JsonLongitude
    latitude: JsonLatitude

    @field_validator("longitude", "latitude", mode="before")
    @classmethod
    def reject_string_coordinates(cls, value: object) -> object:
        if isinstance(value, str):
            raise ValueError("coordinates must use JSON numbers")
        return value


class ItineraryActivity(MessageModel):
    title: ItineraryText
    start_time: datetime
    end_time: datetime
    estimated_cost: JsonDecimal
    source: Literal["AMAP", "DEMO"]
    provider_poi_id: ProviderPoiId | None = None
    coordinates: ActivityCoordinates | None = None
    address: AddressText | None = None

    @model_validator(mode="after")
    def validate_source_metadata(self) -> Self:
        metadata = (self.provider_poi_id, self.coordinates, self.address)
        if self.source == "AMAP" and any(value is None for value in metadata):
            raise ValueError("AMAP activity requires provider metadata")
        if self.source == "DEMO" and any(value is not None for value in metadata):
            raise ValueError("DEMO activity must not contain provider metadata")
        return self


class TransitLeg(MessageModel):
    from_activity_index: int = Field(strict=True, ge=0)
    to_activity_index: int = Field(strict=True, ge=1)
    mode: Literal["WALKING"]
    distance_meters: int = Field(strict=True, ge=0, le=40_100_000)
    duration_seconds: int = Field(strict=True, ge=0, le=31_536_000)
    provider: Literal["AMAP", "DEMO"]
    estimated: bool = Field(strict=True)
    polyline: tuple[ActivityCoordinates, ...] = Field(min_length=1, max_length=5_000)

    @model_validator(mode="after")
    def validate_provider_estimate(self) -> Self:
        if (self.provider == "AMAP" and self.estimated) or (
            self.provider == "DEMO" and not self.estimated
        ):
            raise ValueError("transit leg provider and estimated flag must agree")
        return self


class ItineraryDay(MessageModel):
    date: date
    activities: tuple[ItineraryActivity, ...] = Field(min_length=1)
    transit_legs: tuple[TransitLeg, ...]

    @model_validator(mode="after")
    def validate_transit_legs(self) -> Self:
        expected_count = len(self.activities) - 1
        if len(self.transit_legs) != expected_count:
            raise ValueError("transit legs must connect each adjacent activity")
        for index, leg in enumerate(self.transit_legs):
            if leg.from_activity_index != index or leg.to_activity_index != index + 1:
                raise ValueError("transit legs must connect adjacent activities in order")
            earliest_arrival = self.activities[index].end_time + timedelta(
                seconds=leg.duration_seconds
            )
            if earliest_arrival > self.activities[index + 1].start_time:
                raise ValueError("transit leg travel time must fit between activities")
        return self


class Itinerary(MessageModel):
    title: ItineraryText
    days: tuple[ItineraryDay, ...] = Field(min_length=1)
    estimated_total_cost: JsonDecimal


class PlanningCompletedPayload(MessageModel):
    provider: Literal["AMAP", "DEMO"]
    itinerary: Itinerary

    @model_validator(mode="after")
    def validate_activity_sources(self) -> Self:
        if any(
            activity.source != self.provider
            for day in self.itinerary.days
            for activity in day.activities
        ):
            raise ValueError("activity source must match payload provider")
        return self


class PlanningCompletedEvent(MessageModel):
    event_type: Literal["PLANNING_COMPLETED"]
    schema_version: Literal[3]
    event_id: UUID
    trace_id: UUID
    task_id: UUID
    trip_id: UUID
    run_id: UUID
    occurred_at: datetime
    payload: PlanningCompletedPayload
