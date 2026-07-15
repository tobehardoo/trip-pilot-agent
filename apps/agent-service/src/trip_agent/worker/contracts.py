"""Typed message contracts for the planning worker."""

from datetime import date, datetime
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
    PlainSerializer(lambda value: float(value), return_type=float, when_used="json"),
]
type ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
]
type NameText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
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


class DemoActivity(MessageModel):
    title: str
    start_time: datetime
    end_time: datetime
    estimated_cost: JsonDecimal
    source: Literal["DEMO"]


class DemoItineraryDay(MessageModel):
    date: date
    activities: tuple[DemoActivity, ...] = Field(min_length=1)


class DemoItinerary(MessageModel):
    title: str
    days: tuple[DemoItineraryDay, ...] = Field(min_length=1)
    estimated_total_cost: JsonDecimal


class PlanningCompletedPayload(MessageModel):
    provider: Literal["DEMO"]
    itinerary: DemoItinerary


class PlanningCompletedEvent(MessageModel):
    event_type: Literal["PLANNING_COMPLETED"]
    schema_version: Literal[1]
    event_id: UUID
    trace_id: UUID
    task_id: UUID
    trip_id: UUID
    run_id: UUID
    occurred_at: datetime
    payload: PlanningCompletedPayload
