"""Typed message contracts for the planning worker."""

from __future__ import annotations

import datetime as dt
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PlainSerializer,
    SerializerFunctionWrapHandler,
    StringConstraints,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic.alias_generators import to_camel

from trip_agent.domain.shared import (
    CHINA_TIME_ZONE,
    ActivityKind,
    DayType,
    normalize_text,
)
from trip_agent.feasibility.models import FeasibilityReport, FeasibilityStatus

STRUCTURAL_ACTIVITY_KINDS = frozenset({"MEAL", "ACCOMMODATION", "ARRIVAL", "DEPARTURE"})

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
type KnowledgeIdentifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
type KnowledgeMessage = Annotated[
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


class PlaceRef(InboundMessageModel):
    """B13-D — structured place reference from a real search candidate.

    Candidates are never verification evidence: this type carries only
    provider provenance, coordinates and display fields.
    """

    provider: Literal["AMAP", "DEMO"]
    provider_poi_id: ProviderPoiId
    name: NameText
    address: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200)
    ] = ""
    province: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""
    city: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""
    district: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)

    @field_validator("longitude", "latitude", mode="before")
    @classmethod
    def reject_string_coordinates(cls, value: object) -> object:
        if isinstance(value, str):
            raise ValueError("place coordinates must use JSON numbers")
        return value


class PlaceAnchor(InboundMessageModel):
    place_name: NameText
    place_ref: PlaceRef | None = None


class TravelAnchor(PlaceAnchor):
    time: datetime

    @field_validator("time")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("travel anchor time must include a timezone")
        return value


class MealWindow(InboundMessageModel):
    meal_type: Literal["BREAKFAST", "LUNCH", "DINNER"]
    start_time: time
    end_time: time
    # B13-F: DEFAULT is a soft suggestion (never a hard MEAL_WINDOW FAIL),
    # USER is a hard constraint, DISABLED is not projected.  Historical
    # payloads without a source keep USER semantics (never downgraded).
    source: Literal["DEFAULT", "USER", "DISABLED"] = "USER"

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.start_time.tzinfo is not None or self.end_time.tzinfo is not None:
            raise ValueError("meal window times must be local wall-clock values")
        if self.end_time <= self.start_time:
            raise ValueError("meal window endTime must be after startTime")
        return self


class TripConstraints(InboundMessageModel):
    budget_amount: Decimal | None = Field(ge=0)
    travelers: int = Field(strict=True, ge=1, le=50)
    traveler_type: Literal["SOLO", "COUPLE", "FAMILY", "FRIENDS", "BUSINESS"]
    pace: Literal["RELAXED", "BALANCED", "INTENSIVE"]
    preferences: tuple[ShortText, ...] = Field(max_length=30)
    fixed_schedules: tuple[FixedSchedule, ...] = Field(max_length=30)
    arrival: TravelAnchor | None = None
    departure: TravelAnchor | None = None
    accommodation: PlaceAnchor | None = None
    must_visit_places: tuple[NameText, ...] = Field(default=(), max_length=30)
    avoid_places: tuple[NameText, ...] = Field(default=(), max_length=30)
    meal_windows: tuple[MealWindow, ...] = Field(default=(), max_length=3)
    mobility_level: Literal["STANDARD", "REDUCED", "STEP_FREE"] = "STANDARD"
    # B13-D: structured place references, parallel and index-aligned with
    # must_visit_places / avoid_places.  Schema v3 only.
    must_visit_place_refs: tuple[PlaceRef, ...] = Field(default=(), max_length=30)
    avoid_place_refs: tuple[PlaceRef, ...] = Field(default=(), max_length=30)
    schema_version: Literal[1, 2, 3]

    @field_validator("budget_amount", mode="before")
    @classmethod
    def validate_budget_type(cls, value: object) -> object:
        is_json_number = isinstance(value, int | float | Decimal) and not isinstance(value, bool)
        if value is not None and not is_json_number:
            raise ValueError("budgetAmount must be a JSON number or null")
        return value

    @model_validator(mode="after")
    def validate_v2_collections(self) -> Self:
        must = {normalize_text(value) for value in self.must_visit_places}
        avoided = {normalize_text(value) for value in self.avoid_places}
        if must & avoided:
            raise ValueError("mustVisitPlaces and avoidPlaces must not overlap")
        meal_types = [window.meal_type for window in self.meal_windows]
        if len(meal_types) != len(set(meal_types)):
            raise ValueError("mealWindows must not repeat a mealType")
        ordered_windows = sorted(
            self.meal_windows,
            key=lambda window: (window.start_time, window.end_time),
        )
        if any(
            current.start_time < previous.end_time
            for previous, current in zip(ordered_windows, ordered_windows[1:], strict=False)
        ):
            raise ValueError("mealWindows must not overlap")
        return self

    @model_validator(mode="after")
    def validate_place_refs(self) -> Self:
        """Place refs (B13-D) are schema-v3-only and parallel to their names.

        B13_FIX R2 (P0-2): legacy names with an EMPTY refs list are legal —
        they represent historical free text that was never structured.
        Once any ref is present, refs must be exactly parallel to names.
        """
        if self.schema_version < 3:
            if self.must_visit_place_refs or self.avoid_place_refs:
                raise ValueError("place refs require constraint schemaVersion 3")
            if any(
                anchor is not None and anchor.place_ref is not None
                for anchor in (self.arrival, self.departure, self.accommodation)
            ):
                raise ValueError("anchor place refs require constraint schemaVersion 3")
            return self
        for names, refs, label in (
            (self.must_visit_places, self.must_visit_place_refs, "mustVisit"),
            (self.avoid_places, self.avoid_place_refs, "avoid"),
        ):
            if refs and len(refs) != len(names):
                raise ValueError(f"{label}PlaceRefs must be parallel to {label}Places")
            for name, ref in zip(names, refs, strict=False):
                if normalize_text(ref.name) != normalize_text(name):
                    raise ValueError(f"{label}PlaceRef name must match its place name")
        return self


class GuideFactEvidence(InboundMessageModel):
    guide_import_id: UUID
    fact_id: UUID
    category: Literal[
        "ATTRACTION",
        "DINING",
        "TRANSPORT",
        "TIMING",
        "COST",
        "QUEUE",
        "RESERVATION",
        "LOCATION",
        "WEATHER",
        "TIP",
    ]
    statement: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)
    ]
    evidence: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)
    ]
    source_type: Literal[
        "PUBLIC_GUIDE_URL",
        "PASTED_TEXT",
        "TEXT_FILE",
        "XIAOHONGSHU_SHARED_TEXT",
        "IMAGE_OCR",
        "CITY_INTELLIGENCE",
        "OFFICIAL_ATTRACTION",
        "OFFICIAL_TOURISM",
    ] = "PUBLIC_GUIDE_URL"
    source_url: AnyHttpUrl
    source_host: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=253)
    ]
    source_title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
    ]
    confidence: float = Field(ge=0, le=1)
    effective_date: date | None = None
    observed_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.observed_at.utcoffset() is None or self.expires_at.utcoffset() is None:
            raise ValueError("guide evidence timestamps must include a timezone")
        if self.expires_at <= self.observed_at:
            raise ValueError("guide evidence expiresAt must be after observedAt")
        return self


class GuideEvidenceSnapshot(InboundMessageModel):
    facts: tuple[GuideFactEvidence, ...] = Field(default=(), max_length=100)


class PlanningContextSource(InboundMessageModel):
    source_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
    ]
    source_type: ShortText
    source_url: AnyHttpUrl | None = None
    reliability_level: ShortText


class PlanningContextFact(InboundMessageModel):
    fact_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    category: Literal[
        "ADDRESS",
        "COORDINATES",
        "OPENING_HOURS",
        "TEMPORARY_CLOSURE",
        "TICKET_PRICE",
        "REFERENCE_SPEND",
        "RESERVATION_REQUIREMENT",
        "RESERVATION_ENTRY",
        "TRANSPORT_ADVICE",
        "WEATHER",
        "VENUE_ENVIRONMENT",
        "ATTRACTION_IDENTITY",
        "ATTRACTION",
        "DINING",
        "TRANSPORT",
        "TIMING",
        "COST",
        "QUEUE",
        "RESERVATION",
        "LOCATION",
        "TIP",
    ]
    statement: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    normalized_value: dict[str, JsonValue] | None = None
    evidence: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    effective_date: date | None = None
    checked_at: datetime
    expires_at: datetime
    stale: bool
    source_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
    ]
    source_type: ShortText
    source_url: AnyHttpUrl | None = None
    reliability_level: ShortText
    source_reviewed: bool
    hard_constraint_eligible: bool

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.checked_at.utcoffset() is None or self.expires_at.utcoffset() is None:
            raise ValueError("planning fact timestamps must include a timezone")
        if self.expires_at <= self.checked_at:
            raise ValueError("planning fact expiresAt must be after checkedAt")
        if self.stale and self.hard_constraint_eligible:
            raise ValueError("stale planning facts cannot form hard constraints")
        if self.hard_constraint_eligible and (
            not self.source_reviewed
            or self.reliability_level not in {"OFFICIAL_ATTRACTION", "OFFICIAL_TOURISM"}
        ):
            raise ValueError("hard constraints require a reviewed official source")
        return self


class PlanningContextConflict(InboundMessageModel):
    selected_fact_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    conflict_fact_ids: tuple[str, ...] = Field(default=(), max_length=100)
    downgraded_fact_ids: tuple[str, ...] = Field(default=(), max_length=100)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]
    needs_manual_review: bool


class PlanningContextExcludedFact(InboundMessageModel):
    fact_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    category: ShortText
    statement: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    reason: ShortText


class PlanningContextDiagnostic(InboundMessageModel):
    code: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ] = None
    message: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ] = None
    refresh_status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "PARTIAL", "FAILED"] | None = None


class PlanningContextSnapshot(InboundMessageModel):
    snapshot_id: UUID
    schema_version: Literal[3]
    trip_id: UUID
    planning_task_id: UUID
    city: NameText
    travel_start_date: date
    travel_end_date: date
    generated_at: datetime
    stale: bool
    sources: tuple[PlanningContextSource, ...] = Field(default=(), max_length=100)
    facts: tuple[PlanningContextFact, ...] = Field(default=(), max_length=200)
    conflicts: tuple[PlanningContextConflict, ...] = Field(default=(), max_length=200)
    excluded_facts: tuple[PlanningContextExcludedFact, ...] = Field(default=(), max_length=200)
    diagnostics: tuple[PlanningContextDiagnostic, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.generated_at.utcoffset() is None:
            raise ValueError("planning context generatedAt must include a timezone")
        if self.travel_end_date < self.travel_start_date:
            raise ValueError("planning context dates are invalid")
        if any(
            fact.effective_date is not None
            and not self.travel_start_date <= fact.effective_date <= self.travel_end_date
            for fact in self.facts
        ):
            raise ValueError("planning facts must apply to the trip date range")
        if any(fact.stale for fact in self.facts) and not self.stale:
            raise ValueError("a context containing stale facts must be stale")
        return self


class TripSnapshot(InboundMessageModel):
    title: NameText
    destination: NameText
    start_date: date
    end_date: date
    status: Literal["DRAFT"]
    version: int = Field(strict=True, ge=0)
    constraints: TripConstraints
    # B13_FIX R1 (P0-1): authoritative boundary times.  The Java producer
    # always serializes these fields (null for legacy date-only trips); the
    # planner must prefer them over legacy constraint anchors.
    arrival_at: datetime | None = None
    departure_at: datetime | None = None

    @field_validator("arrival_at", "departure_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("snapshot boundary times must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("trip endDate must not be before startDate")
        if (self.end_date - self.start_date).days + 1 > 7:
            raise ValueError("trip duration must not exceed 7 days")
        for schedule in self.constraints.fixed_schedules:
            starts_before_trip = (
                schedule.start_time.astimezone(CHINA_TIME_ZONE).date() < self.start_date
            )
            ends_after_trip = schedule.end_time.astimezone(CHINA_TIME_ZONE).date() > self.end_date
            if starts_before_trip or ends_after_trip:
                raise ValueError("fixed schedules must fall within trip dates")
        for anchor in (self.constraints.arrival, self.constraints.departure):
            if anchor is not None and not (
                self.start_date <= anchor.time.astimezone(CHINA_TIME_ZONE).date() <= self.end_date
            ):
                raise ValueError("travel anchor times must fall within trip dates")
        arrival = self.constraints.arrival
        departure = self.constraints.departure
        if arrival is not None and departure is not None and departure.time <= arrival.time:
            raise ValueError("departure time must be after arrival time")
        if (
            self.arrival_at is not None
            and self.departure_at is not None
            and self.departure_at <= self.arrival_at
        ):
            raise ValueError("departureAt must be after arrivalAt")
        return self


class PlanningCreatePayload(InboundMessageModel):
    task_type: Literal["CREATE"]
    baseline_trip_version: int = Field(strict=True, ge=0)
    idempotency_key: UUID
    trip: TripSnapshot
    guide_evidence: GuideEvidenceSnapshot = GuideEvidenceSnapshot()
    planning_context: PlanningContextSnapshot | None = None

    @model_validator(mode="after")
    def validate_baseline_version(self) -> Self:
        if self.baseline_trip_version != self.trip.version:
            raise ValueError("baselineTripVersion must match trip.version")
        return self


class PlanningCreateCommand(InboundMessageModel):
    event_type: Literal["PLANNING_CREATE_REQUESTED"]
    schema_version: Literal[1, 2, 3, 4]
    event_id: UUID
    trace_id: UUID
    task_id: UUID
    trip_id: UUID
    occurred_at: datetime
    payload: PlanningCreatePayload

    @model_validator(mode="after")
    def validate_version_alignment(self) -> Self:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurredAt must include a timezone")
        constraints = self.payload.trip.constraints
        if self.schema_version == 4:
            # B13_FIX R1: v4 always carries the snapshot boundary fields
            # (values may be null for legacy date-only trips); constraints
            # may be schema 2 (no place refs) or 3 (mixed/structured).
            if constraints.schema_version not in {2, 3}:
                raise ValueError("schemaVersion 4 requires constraint schemaVersion 2 or 3")
            snapshot = self.payload.trip
            if "arrival_at" not in snapshot.model_fields_set:
                raise ValueError("schemaVersion 4 requires snapshot arrivalAt")
            if "departure_at" not in snapshot.model_fields_set:
                raise ValueError("schemaVersion 4 requires snapshot departureAt")
        elif constraints.schema_version != min(self.schema_version, 2):
            raise ValueError("command and constraint schemaVersion are incompatible")
        if self.schema_version == 1 and (
            constraints.arrival is not None
            or constraints.departure is not None
            or constraints.accommodation is not None
            or constraints.must_visit_places
            or constraints.avoid_places
            or constraints.meal_windows
            or constraints.mobility_level != "STANDARD"
            or self.payload.guide_evidence.facts
        ):
            raise ValueError("v2 context and guide evidence require schemaVersion 2")
        if any(
            fact.observed_at > self.occurred_at or fact.expires_at <= self.occurred_at
            for fact in self.payload.guide_evidence.facts
        ):
            raise ValueError("guide evidence must be fresh at command occurredAt")
        context = self.payload.planning_context
        if self.schema_version < 3 and context is not None:
            raise ValueError("planning context requires schemaVersion 3")
        if self.schema_version >= 3:
            if context is None:
                raise ValueError(f"schemaVersion {self.schema_version} requires a planning context")
            if (
                context.trip_id != self.trip_id
                or context.planning_task_id != self.task_id
                or context.city != self.payload.trip.destination
                or context.travel_start_date != self.payload.trip.start_date
                or context.travel_end_date != self.payload.trip.end_date
            ):
                raise ValueError("planning context identity must match the command")
            if context.generated_at > self.occurred_at:
                raise ValueError("planning context cannot be generated after the command")
        return self


# normalize_text is imported from trip_agent.domain.shared


class PlanningCancelCommand(InboundMessageModel):
    event_type: Literal["PLANNING_CANCEL_REQUESTED"]
    schema_version: Literal[1]
    event_id: UUID
    trace_id: UUID
    task_id: UUID
    trip_id: UUID
    occurred_at: datetime

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


class FallbackOperation(MessageModel):
    operation: Literal["PLANNING", "REPLANNING", "ROUTE"]
    transit_id: UUID | None = None
    from_activity_id: UUID | None = None
    to_activity_id: UUID | None = None
    requested_mode: Literal["REAL_WITH_EXPLICIT_FALLBACK"]
    actual_provider: Literal["DEMO"]
    error_category: Literal[
        "QUOTA_EXCEEDED",
        "RATE_LIMITED",
        "TIMEOUT",
        "NETWORK_ERROR",
        "PROVIDER_UNAVAILABLE",
        "MALFORMED_RESPONSE",
    ]
    error_code: ShortText
    retry_count: int = Field(strict=True, ge=0, le=10)

    @model_validator(mode="after")
    def validate_route_identity(self) -> Self:
        route_ids = (self.transit_id, self.from_activity_id, self.to_activity_id)
        if self.operation == "ROUTE" and any(value is None for value in route_ids):
            raise ValueError("route fallback requires stable transit and activity IDs")
        if self.operation != "ROUTE" and any(value is not None for value in route_ids):
            raise ValueError("whole-plan fallback must not claim a transit identity")
        return self


class ItineraryActivity(MessageModel):
    activity_id: UUID | None = None
    title: ItineraryText
    start_time: datetime
    end_time: datetime
    estimated_cost: JsonDecimal
    # V1 Data-Truth: where this activity's cost came from.  In-process only
    # (excluded from serialization, mirroring ``meal_type``) so the
    # completion wire body stays byte-identical; Java-sourced snapshots
    # default to UNKNOWN and are treated as unverifiable by consumers.
    cost_source: Literal[
        "PROVIDER",
        "RULE_ESTIMATE",
        "CATEGORY_ESTIMATE",
        "CITY_ESTIMATE",
        "DEMO",
        "UNKNOWN",
    ] = Field(default="UNKNOWN", exclude=True)
    source: Literal["AMAP", "DEMO"]
    provider_poi_id: ProviderPoiId | None = None
    coordinates: ActivityCoordinates | None = None
    address: AddressText | None = None
    type_code: str | None = None
    type_name: str | None = None
    kind: ActivityKind | None = None
    time_fixed: bool | None = None
    # B13_FIX R3 (P0-3): the meal type an itinerary MEAL activity stands for.
    # In-process identity only: the field is excluded from serialization so
    # the published completion v9 wire body stays byte-identical (the Java
    # parser rejects unknown properties).  None for Java-sourced snapshots,
    # which the validation projection then treats as unverifiable.
    meal_type: Literal["BREAKFAST", "LUNCH", "DINNER"] | None = Field(
        default=None, exclude=True
    )
    # Candidate-validation only. Existing create/replan events omit it;
    # explicit edits preserve the persistence lock without changing legacy
    # semantics.
    locked: bool | None = None

    @model_validator(mode="after")
    def validate_source_metadata(self) -> Self:
        metadata = (self.provider_poi_id, self.coordinates, self.address)
        if self.source == "DEMO" and any(value is not None for value in metadata):
            raise ValueError("DEMO activity must not contain provider metadata")
        if self.source == "AMAP":
            structural = self.kind is not None and self.kind in STRUCTURAL_ACTIVITY_KINDS
            if structural and not any(value is not None for value in metadata):
                return self
            if any(value is None for value in metadata):
                raise ValueError("AMAP activity requires provider metadata")
        return self


type ItineraryTransitMode = Literal["WALKING", "TRANSIT", "DRIVING", "TAXI"]


class TransitLeg(MessageModel):
    transit_id: UUID | None = None
    from_activity_index: int = Field(strict=True, ge=0)
    to_activity_index: int = Field(strict=True, ge=1)
    mode: ItineraryTransitMode
    distance_meters: int = Field(strict=True, ge=0, le=40_100_000)
    duration_seconds: int = Field(strict=True, ge=0, le=31_536_000)
    provider: Literal["AMAP", "DEMO"]
    estimated: bool = Field(strict=True)
    polyline: tuple[ActivityCoordinates, ...] = Field(min_length=1, max_length=5_000)
    estimated_cost: JsonDecimal | None = Field(default=None, exclude=True)
    cost_source: Literal["PROVIDER", "RULE_ESTIMATE", "DEMO", "UNKNOWN"] = Field(
        default="UNKNOWN", exclude=True
    )
    fallback_operation: FallbackOperation | None = Field(default=None, exclude=True)
    # Candidate-validation only; None keeps historic v9/review payloads valid.
    locked: bool | None = None

    @model_validator(mode="after")
    def validate_cost(self) -> Self:
        if self.estimated_cost is not None and self.estimated_cost < 0:
            raise ValueError("transit leg estimated cost must not be negative")
        return self

    @model_validator(mode="after")
    def validate_provider_estimate(self) -> Self:
        if (self.provider == "AMAP" and self.estimated) or (
            self.provider == "DEMO" and not self.estimated
        ):
            raise ValueError("transit leg provider and estimated flag must agree")
        return self


class ItineraryDay(MessageModel):
    date: date
    day_type: DayType | None = None
    activities: tuple[ItineraryActivity, ...] = Field(min_length=1)
    transit_legs: tuple[TransitLeg, ...]

    @model_validator(mode="after")
    def validate_transit_legs(self) -> Self:
        expected_pairs = {(index, index + 1) for index in range(len(self.activities) - 1)}
        actual_pairs: set[tuple[int, int]] = set()
        for leg in self.transit_legs:
            endpoints = (leg.from_activity_index, leg.to_activity_index)
            if endpoints not in expected_pairs:
                raise ValueError("transit legs must connect adjacent activities in order")
            if endpoints in actual_pairs:
                raise ValueError("transit legs must use unique adjacent activity endpoints")
            actual_pairs.add(endpoints)
            earliest_arrival = self.activities[leg.from_activity_index].end_time + timedelta(
                seconds=leg.duration_seconds
            )
            if earliest_arrival > self.activities[leg.to_activity_index].start_time:
                raise ValueError("transit leg travel time must fit between activities")
        # Gaps between adjacent activities are allowed: structural nodes
        # (e.g. an unresolved meal) intentionally have no transit leg.
        if len(self.transit_legs) > len(expected_pairs):
            raise ValueError("transit legs cannot exceed adjacent activity pairs")
        return self


class AccommodationStatus(MessageModel):
    """End-to-end accommodation resolution status carried on the itinerary.

    CONFIRMED — a provider POI with coordinates was projected as the hotel
    node.  AREA_ESTIMATED — a structured region estimate (AMap transient
    projection; not currently produced by any itinerary entry point).  The
    rest stays UNRESOLVED — the user's accommodation label could not be
    located, and the system never fabricates a confirmation.
    """

    status: Literal["CONFIRMED", "AREA_ESTIMATED", "UNRESOLVED"]
    place_name: str | None = None


class Itinerary(MessageModel):
    title: ItineraryText
    days: tuple[ItineraryDay, ...] = Field(min_length=1)
    estimated_total_cost: JsonDecimal
    # Optional so older producers keep emitting compatible events; Java and
    # the Web use it to show whether the hotel is confirmed or unresolved.
    accommodation: AccommodationStatus | None = None


class KnowledgeCitationSnapshot(MessageModel):
    document_id: KnowledgeIdentifier
    document_version: int = Field(strict=True, ge=1)
    chunk_id: KnowledgeIdentifier
    chunk_index: int = Field(strict=True, ge=0)
    title: ItineraryText
    source_url: AnyHttpUrl
    source_name: NameText
    collected_at: datetime
    reliability_level: ShortText
    similarity: float = Field(ge=-1, le=1)

    @field_validator("collected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("citation collectedAt must include a timezone")
        return value


class KnowledgeFreshness(MessageModel):
    status: Literal["FRESH", "STALE", "UNAVAILABLE"]
    checked_at: datetime | None = None
    stale_reason: ShortText | None = None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.checked_at is not None and self.checked_at.utcoffset() is None:
            raise ValueError("knowledge freshness checkedAt must include a timezone")
        if self.status == "UNAVAILABLE" and (
            self.checked_at is not None or self.stale_reason is not None
        ):
            raise ValueError("unavailable freshness must not contain verification details")
        if self.status == "FRESH" and self.stale_reason is not None:
            raise ValueError("fresh knowledge must not contain staleReason")
        if self.status != "UNAVAILABLE" and self.checked_at is None:
            raise ValueError("available freshness requires checkedAt")
        return self


class KnowledgeEvidence(MessageModel):
    status: Literal["REAL", "DEMO", "UNAVAILABLE"]
    query: ItineraryText
    citations: tuple[KnowledgeCitationSnapshot, ...] = Field(max_length=20)
    freshness: KnowledgeFreshness
    message: KnowledgeMessage | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.status == "REAL":
            if not self.citations:
                raise ValueError("real knowledge evidence requires citations")
            if self.freshness.status == "UNAVAILABLE":
                raise ValueError("real knowledge evidence requires freshness")
            if self.message is not None:
                raise ValueError("real knowledge evidence must not contain a fallback message")
            return self
        if self.citations:
            raise ValueError("non-real knowledge evidence must not contain citations")
        if self.freshness.status != "UNAVAILABLE" or self.message is None:
            raise ValueError("non-real knowledge evidence requires an unavailable reason")
        return self


class ReplanItineraryDay(InboundMessageModel):
    date: date
    day_type: DayType | None = None
    activities: tuple[ItineraryActivity, ...] = Field(min_length=1)
    transit_legs: tuple[TransitLeg, ...]

    @model_validator(mode="after")
    def validate_present_transit_legs(self) -> Self:
        expected_pairs = {(index, index + 1) for index in range(len(self.activities) - 1)}
        actual_pairs: set[tuple[int, int]] = set()
        for leg in self.transit_legs:
            endpoints = (leg.from_activity_index, leg.to_activity_index)
            if endpoints not in expected_pairs:
                raise ValueError("transit legs must connect adjacent activities in order")
            if endpoints in actual_pairs:
                raise ValueError("transit legs must use unique adjacent activity endpoints")
            actual_pairs.add(endpoints)
        return self

    def to_itinerary_day(self) -> ItineraryDay:
        return ItineraryDay(
            date=self.date,
            day_type=self.day_type,
            activities=self.activities,
            transit_legs=self.transit_legs,
        )


class ReplanItinerarySnapshot(InboundMessageModel):
    title: ItineraryText
    provider: Literal["AMAP", "DEMO"]
    days: tuple[ReplanItineraryDay, ...] = Field(min_length=1)
    estimated_total_cost: JsonDecimal

    @model_validator(mode="after")
    def validate_activity_sources(self) -> Self:
        if any(
            activity.source != self.provider for day in self.days for activity in day.activities
        ):
            raise ValueError("replan activity source must match itinerary provider")
        return self


def _forbid_taxi_on_v2_wire(itinerary: Itinerary | ReplanItinerarySnapshot) -> None:
    """Keep TAXI as a Java persistence intent, never a Python provider mode."""
    if any(
        leg.mode == "TAXI"
        for day in itinerary.days
        for leg in day.transit_legs
    ):
        raise ValueError("schemaVersion 2/11 wire itineraries forbid TAXI mode")


def _forbid_raw_taxi_on_wire(value: object) -> object:
    if not isinstance(value, dict):
        return value
    payload = value.get("payload")
    itinerary = payload.get("itinerary") if isinstance(payload, dict) else None
    days = itinerary.get("days", ()) if isinstance(itinerary, dict) else ()
    if any(
        isinstance(leg, dict) and leg.get("mode") == "TAXI"
        for day in days
        if isinstance(day, dict)
        for leg in day.get("transitLegs", day.get("transit_legs", ()))
    ):
        raise ValueError("schemaVersion 2/11 wire itineraries forbid TAXI mode")
    return value


def _inject_activity_cost_sources(
    wire: dict[str, object],
    itinerary: Itinerary,
) -> dict[str, object]:
    """Surface per-activity ``costSource`` on the wire.

    ``ItineraryActivity.cost_source`` is excluded from serialization so the
    pre-vN completion bodies stay byte-identical; mirroring the v11 transit
    leg cost injection, we write it back onto each serialized activity so
    consumers (Java parser, Web) can tell estimator output from real provider
    price.  Missing values fall back to "UNKNOWN".
    """
    payload = wire.get("payload")
    wire_itinerary = payload.get("itinerary") if isinstance(payload, dict) else None
    wire_days = wire_itinerary.get("days", ()) if isinstance(wire_itinerary, dict) else ()
    for wire_day, day in zip(wire_days, itinerary.days, strict=False):
        if not isinstance(wire_day, dict):
            continue
        wire_activities = wire_day.get("activities", ())
        for wire_activity, activity in zip(
            wire_activities, day.activities, strict=False
        ):
            if not isinstance(wire_activity, dict):
                continue
            wire_activity["costSource"] = activity.cost_source or "UNKNOWN"
    return wire


def _inject_v11_transit_costs(
    wire: dict[str, object],
    itinerary: Itinerary,
) -> dict[str, object]:
    payload = wire.get("payload")
    wire_itinerary = payload.get("itinerary") if isinstance(payload, dict) else None
    wire_days = wire_itinerary.get("days", ()) if isinstance(wire_itinerary, dict) else ()
    for wire_day, day in zip(wire_days, itinerary.days, strict=False):
        if not isinstance(wire_day, dict):
            continue
        wire_legs = wire_day.get("transitLegs", wire_day.get("transit_legs", ()))
        for wire_leg, leg in zip(wire_legs, day.transit_legs, strict=False):
            if not isinstance(wire_leg, dict):
                continue
            if leg.estimated_cost is not None:
                wire_leg["estimatedCost"] = float(leg.estimated_cost)
            wire_leg["costSource"] = leg.cost_source
    wire_report = payload.get("feasibilityReport", payload.get("feasibility_report"))
    if isinstance(wire_itinerary, dict) and isinstance(wire_report, dict):
        from trip_agent.feasibility.fingerprint import (
            compute_serialized_itinerary_fingerprint,
        )

        fingerprint_key = (
            "itineraryFingerprint"
            if "feasibilityReport" in payload
            else "itinerary_fingerprint"
        )
        wire_report[fingerprint_key] = compute_serialized_itinerary_fingerprint(
            wire_itinerary
        )
    return wire


class PlanningReplanPayload(InboundMessageModel):
    task_type: Literal["REPLAN"]
    baseline_trip_version: int = Field(strict=True, ge=0)
    baseline_itinerary_version_id: UUID
    idempotency_key: UUID
    impacted_dates: tuple[date, ...] = Field(min_length=1, max_length=7)
    trip: TripSnapshot
    itinerary: ReplanItinerarySnapshot
    knowledge: KnowledgeEvidence

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.baseline_trip_version != self.trip.version:
            raise ValueError("baselineTripVersion must match trip.version")
        if len(self.impacted_dates) != len(set(self.impacted_dates)):
            raise ValueError("impactedDates must not contain duplicates")
        expected_dates = tuple(
            self.trip.start_date + timedelta(days=offset)
            for offset in range((self.trip.end_date - self.trip.start_date).days + 1)
        )
        if tuple(day.date for day in self.itinerary.days) != expected_dates:
            raise ValueError("replan itinerary must contain every trip date in order")
        expected_date_set = set(expected_dates)
        if any(value not in expected_date_set for value in self.impacted_dates):
            raise ValueError("impactedDates must fall within the itinerary")
        impacted = set(self.impacted_dates)
        for day in self.itinerary.days:
            if day.date not in impacted and day.transit_legs:
                day.to_itinerary_day()
        return self


class PlanningReplanCommand(InboundMessageModel):
    event_type: Literal["PLANNING_REPLAN_REQUESTED"]
    schema_version: Literal[1, 2]
    event_id: UUID
    trace_id: UUID
    task_id: UUID
    trip_id: UUID
    occurred_at: datetime
    payload: PlanningReplanPayload

    @model_validator(mode="before")
    @classmethod
    def require_raw_technical_route_modes(cls, value: object) -> object:
        return _forbid_raw_taxi_on_wire(value)

    @model_validator(mode="after")
    def validate_occurred_at(self) -> Self:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurredAt must include a timezone")
        if self.schema_version == 2:
            # B13_FIX R1: v2 snapshots always carry the boundary fields.
            snapshot = self.payload.trip
            if "arrival_at" not in snapshot.model_fields_set:
                raise ValueError("schemaVersion 2 requires snapshot arrivalAt")
            if "departure_at" not in snapshot.model_fields_set:
                raise ValueError("schemaVersion 2 requires snapshot departureAt")
            _forbid_taxi_on_v2_wire(self.payload.itinerary)
        return self


class PlanningFactImpact(MessageModel):
    fact_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    category: ShortText
    date: dt.date | None = None
    effect: ShortText
    target_poi_id: ProviderPoiId | None = None
    target_name: NameText | None = None
    reason: KnowledgeMessage
    source_name: NameText
    source_type: ShortText
    source_url: AnyHttpUrl | None = None
    reliability_level: ShortText
    checked_at: datetime
    evidence: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    stale: bool
    conflicted: bool
    refresh_failed: bool

    @model_serializer(mode="wrap")
    def _omit_none_optional_fields(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, object]:
        """Omit every optional-not-nullable field instead of emitting null.

        The v10 schema (and Java ``PlanningCompletedEventParser`` /
        ``PlanningReviewRequiredEventParser``) require ``date``/``targetPoiId``/
        ``targetName``/``sourceUrl`` to be non-null strings whenever the
        property is present; an absent value (e.g. a city-wide weather impact
        or a stale-fact warning without a target) must be expressed by omitting
        the field, never by ``null``.  This mirrors the schema contract: these
        fields are optional, not nullable.
        """
        data = handler(self)
        if self.date is None:
            data.pop("date", None)
        if self.target_poi_id is None:
            data.pop("targetPoiId", None)
            data.pop("target_poi_id", None)
        if self.target_name is None:
            data.pop("targetName", None)
            data.pop("target_name", None)
        if self.source_url is None:
            data.pop("sourceUrl", None)
            data.pop("source_url", None)
        return data

    @model_validator(mode="after")
    def validate_checked_at(self) -> Self:
        if self.checked_at.utcoffset() is None:
            raise ValueError("fact impact checkedAt must include a timezone")
        return self


class ProviderProvenance(MessageModel):
    requested_provider_mode: Literal[
        "DEMO_ONLY",
        "REAL_ONLY",
        "REAL_WITH_EXPLICIT_FALLBACK",
    ]
    primary_provider: Literal["AMAP", "DEMO"]
    actual_providers: tuple[Literal["AMAP", "DEMO"], ...] = Field(min_length=1)
    fallback_attempted: bool = Field(strict=True)
    fallback_succeeded: bool = Field(strict=True)
    fallback_reason: ShortText | None = None
    fallback_operations: tuple[FallbackOperation, ...] = ()

    @model_validator(mode="after")
    def validate_and_normalize(self) -> Self:
        provider_order = {"AMAP": 0, "DEMO": 1}
        actual_providers = tuple(sorted(set(self.actual_providers), key=provider_order.__getitem__))
        operation_keys: set[tuple[object, ...]] = set()
        operations: list[FallbackOperation] = []
        for operation in sorted(
            self.fallback_operations,
            key=lambda item: (
                item.operation,
                str(item.transit_id or ""),
                str(item.from_activity_id or ""),
                str(item.to_activity_id or ""),
                item.error_category,
                item.error_code,
                item.retry_count,
            ),
        ):
            key = (
                operation.operation,
                operation.transit_id,
                operation.from_activity_id,
                operation.to_activity_id,
                operation.requested_mode,
                operation.actual_provider,
                operation.error_category,
                operation.error_code,
                operation.retry_count,
            )
            if key not in operation_keys:
                operation_keys.add(key)
                operations.append(operation)
        object.__setattr__(self, "actual_providers", actual_providers)
        object.__setattr__(self, "fallback_operations", tuple(operations))
        if len(self.fallback_operations) > 100:
            raise ValueError("fallback operation evidence exceeds the supported limit")

        if self.fallback_attempted != self.fallback_succeeded:
            raise ValueError("successful completion cannot contain a failed fallback")
        if self.fallback_attempted:
            if not self.fallback_operations or self.fallback_reason is None:
                raise ValueError("successful fallback requires reason and operation evidence")
        elif self.fallback_operations or self.fallback_reason is not None:
            raise ValueError("non-fallback completion must not contain fallback evidence")

        if self.requested_provider_mode == "DEMO_ONLY":
            if self.primary_provider != "DEMO" or self.actual_providers != ("DEMO",):
                raise ValueError("DEMO_ONLY completion must only contain DEMO evidence")
            if self.fallback_attempted:
                raise ValueError("DEMO_ONLY completion cannot be a fallback")
        elif self.requested_provider_mode == "REAL_ONLY":
            if self.primary_provider != "AMAP" or self.actual_providers != ("AMAP",):
                raise ValueError("REAL_ONLY completion must only contain AMAP evidence")
            if self.fallback_attempted:
                raise ValueError("REAL_ONLY completion cannot use DEMO fallback")
        else:
            if self.primary_provider != "AMAP":
                raise ValueError("explicit fallback mode must have AMAP as primary provider")
            if self.fallback_attempted and "DEMO" not in self.actual_providers:
                raise ValueError("successful fallback must record DEMO as an actual provider")
            if not self.fallback_attempted and self.actual_providers != ("AMAP",):
                raise ValueError("unused explicit fallback must remain pure AMAP")

        if any(
            operation.requested_mode != self.requested_provider_mode
            for operation in self.fallback_operations
        ):
            raise ValueError("fallback operation mode must match top-level provenance")
        return self


# ── B6: authoritative outcome events (v10/v11 completion / review v2) ──────


class PlanningCompletedPayloadV10(MessageModel):
    """v10 completion payload: authoritative completion evidence.

    Carries the full v9 completion contract (required PlanEvaluation plus
    a feasibility report bound to the itinerary fingerprint) with explicit
    blocker semantics on top: ``has_blocker`` mirrors the report's derived
    blocker state so the Java side never guesses from ``warnings.length``.
    A v10 completion may carry an UNVERIFIED report as long as no blocker
    exists (Information Missing != Planning Failed); VERIFIED reports keep
    has_blocker=False.

    F-3c: the V9 base class was terminated; its fields and validators are
    inlined here so V10 stands alone while v11 reuses the same payload.
    """

    provider: Literal["AMAP", "DEMO"]
    itinerary: Itinerary
    knowledge: KnowledgeEvidence
    fact_impacts: tuple[PlanningFactImpact, ...] = Field(default=(), max_length=500)
    provider_provenance: ProviderProvenance | None = None
    evaluation: object
    feasibility_report: FeasibilityReport
    has_blocker: bool

    @field_validator("evaluation", mode="before")
    @classmethod
    def _normalize_evaluation(cls, value: object) -> object:
        """Accept only a PlanEvaluation (deferred import avoids a cycle)."""
        if value is None:
            raise ValueError("evaluation is required for completion")
        from trip_agent.evaluation.models import PlanEvaluation  # noqa: PLC0415

        if isinstance(value, PlanEvaluation):
            return value
        if isinstance(value, dict):
            return PlanEvaluation.model_validate(value)
        raise ValueError("evaluation must be a PlanEvaluation")

    @model_validator(mode="after")
    def validate_activity_sources(self) -> Self:
        if any(
            activity.source != self.provider
            for day in self.itinerary.days
            for activity in day.activities
        ):
            raise ValueError("activity source must match payload provider")
        return self

    @model_validator(mode="after")
    def validate_report_fingerprint(self) -> Self:
        from trip_agent.feasibility.fingerprint import compute_itinerary_fingerprint

        expected = compute_itinerary_fingerprint(self.itinerary)
        if self.feasibility_report.itinerary_fingerprint != expected:
            raise ValueError("feasibility report fingerprint must match the payload itinerary")
        return self

    @model_validator(mode="after")
    def blocker_consistent(self) -> Self:
        if self.has_blocker != self.feasibility_report.has_blocker:
            raise ValueError("has_blocker must match the feasibility report blocker state")
        if self.has_blocker:
            raise ValueError("completion must not carry a blocker report")
        return self


class PlanningCompletedEventV11(MessageModel):
    event_type: Literal["PLANNING_COMPLETED"]
    schema_version: Literal[11]
    event_id: UUID
    trace_id: UUID
    task_id: UUID
    trip_id: UUID
    run_id: UUID
    occurred_at: datetime
    payload: PlanningCompletedPayloadV10

    @model_validator(mode="before")
    @classmethod
    def require_raw_technical_route_modes(cls, value: object) -> object:
        return _forbid_raw_taxi_on_wire(value)

    @model_validator(mode="after")
    def require_savable_report(self) -> Self:
        if self.payload.feasibility_report.has_blocker:
            raise ValueError("v11 completion requires a savable (no-blocker) feasibility report")
        _forbid_taxi_on_v2_wire(self.payload.itinerary)
        return self

    @model_serializer(mode="wrap")
    def include_transit_costs(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, object]:
        wire = _inject_activity_cost_sources(handler(self), self.payload.itinerary)
        return _inject_v11_transit_costs(wire, self.payload.itinerary)


class PlanningReviewRequiredPayload(MessageModel):
    status: Literal["WAITING_USER"]
    provider: Literal["AMAP", "DEMO"]
    itinerary: Itinerary
    knowledge: KnowledgeEvidence
    fact_impacts: tuple[PlanningFactImpact, ...] = Field(default=(), max_length=500)
    provider_provenance: ProviderProvenance | None = None
    feasibility_report: FeasibilityReport

    @model_validator(mode="after")
    def validate_activity_sources(self) -> Self:
        if any(
            activity.source != self.provider
            for day in self.itinerary.days
            for activity in day.activities
        ):
            raise ValueError("activity source must match payload provider")
        return self

    @model_validator(mode="after")
    def forbid_verified_report(self) -> Self:
        if self.feasibility_report.status is FeasibilityStatus.VERIFIED:
            raise ValueError("review-required forbids a VERIFIED feasibility report")
        return self

    @model_validator(mode="after")
    def validate_report_fingerprint(self) -> Self:
        from trip_agent.feasibility.fingerprint import compute_itinerary_fingerprint

        expected = compute_itinerary_fingerprint(self.itinerary)
        if self.feasibility_report.itinerary_fingerprint != expected:
            raise ValueError("feasibility report fingerprint must match the payload itinerary")
        return self


class PlanningReviewRequiredEventV2(MessageModel):
    event_type: Literal["PLANNING_REVIEW_REQUIRED"]
    schema_version: Literal[2]
    event_id: UUID
    trace_id: UUID
    task_id: UUID
    trip_id: UUID
    run_id: UUID
    occurred_at: datetime
    payload: PlanningReviewRequiredPayload

    @model_validator(mode="before")
    @classmethod
    def require_raw_technical_route_modes(cls, value: object) -> object:
        return _forbid_raw_taxi_on_wire(value)

    @model_validator(mode="after")
    def require_technical_route_modes(self) -> Self:
        _forbid_taxi_on_v2_wire(self.payload.itinerary)
        return self

    @model_serializer(mode="wrap")
    def include_transit_costs(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, object]:
        wire = _inject_activity_cost_sources(handler(self), self.payload.itinerary)
        return _inject_v11_transit_costs(wire, self.payload.itinerary)


class PlanningConflict(MessageModel):
    code: ShortText
    message: KnowledgeMessage
    affected: tuple[NameText, ...] = Field(min_length=1, max_length=30)


class PlanningRelaxation(MessageModel):
    code: ShortText
    message: KnowledgeMessage


class PlanningFailedPayload(MessageModel):
    status: Literal["FAILED"]
    error_code: ShortText
    error_category: Literal[
        "CONFIGURATION_ERROR",
        "AUTHENTICATION_ERROR",
        "PERMISSION_DENIED",
        "QUOTA_EXCEEDED",
        "RATE_LIMITED",
        "TIMEOUT",
        "NETWORK_ERROR",
        "PROVIDER_UNAVAILABLE",
        "INVALID_REQUEST",
        "NO_RESULT",
        "UNSUPPORTED_MODE",
        "MALFORMED_RESPONSE",
        "DATA_QUALITY_ERROR",
        "PROVIDER_ADAPTER_ERROR",
        "PLANNING_INFEASIBLE",
        "INTERNAL_ERROR",
    ]
    provider: Literal["AMAP", "DEMO", "PLANNER"]
    operation: Literal[
        "CONFIGURATION",
        "PLANNING",
        "REPLANNING",
        "POI_SEARCH",
        "ROUTE",
    ]
    retryable: bool = Field(strict=True)
    retry_count: int = Field(strict=True, ge=0, le=10)
    fallback_attempted: bool = Field(strict=True)
    fallback_succeeded: bool = Field(strict=True)
    safe_message: KnowledgeMessage
    safe_provider_code: ShortText | None = None
    cause_type: ShortText | None = None
    conflicts: tuple[PlanningConflict, ...] = Field(default=(), max_length=20)
    relaxation_suggestions: tuple[PlanningRelaxation, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def validate_fallback_outcome(self) -> Self:
        if self.fallback_succeeded and not self.fallback_attempted:
            raise ValueError("fallbackSucceeded requires fallbackAttempted")
        if self.error_category == "PLANNING_INFEASIBLE" and not self.conflicts:
            raise ValueError("planning infeasibility requires conflicts")
        return self


class PlanningFailedEvent(MessageModel):
    event_type: Literal["PLANNING_FAILED"]
    schema_version: Literal[2]
    event_id: UUID
    trace_id: UUID
    task_id: UUID
    trip_id: UUID
    run_id: UUID
    occurred_at: datetime
    payload: PlanningFailedPayload


type PlanningProgressStage = Literal[
    "TASK_ACCEPTED",
    "CONTEXT_VALIDATING",
    "CITY_FACTS_LOADING",
    "POI_RECALLING",
    "CANDIDATES_RANKING",
    "ROUTES_CALCULATING",
    "CONSTRAINTS_SOLVING",
    "REPAIRING",
    "KNOWLEDGE_RETRIEVING",
    "RESULT_EXPLAINING",
    "RESULT_PUBLISHING",
]
type ProgressStatistic = Annotated[
    int,
    Field(strict=True, ge=0, le=2_147_483_647),
]


class PlanningProgressPayload(MessageModel):
    stage: PlanningProgressStage
    sequence: int = Field(strict=True, ge=1, le=100)
    progress: int = Field(strict=True, ge=0, le=100)
    message: KnowledgeMessage
    statistics: dict[ShortText, ProgressStatistic] = Field(default_factory=dict, max_length=20)


class PlanningProgressEvent(MessageModel):
    event_type: Literal["PLANNING_PROGRESS"]
    schema_version: Literal[1, 2]
    event_id: UUID
    trace_id: UUID
    task_id: UUID
    trip_id: UUID
    occurred_at: datetime
    payload: PlanningProgressPayload

    @model_validator(mode="after")
    def validate_occurred_at(self) -> Self:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurredAt must include a timezone")
        return self

    @model_validator(mode="after")
    def validate_repair_stage(self) -> Self:
        if self.schema_version == 1 and self.payload.stage == "REPAIRING":
            raise ValueError("REPAIRING progress requires schemaVersion 2")
        if self.payload.stage == "REPAIRING":
            if not 1 <= self.payload.statistics.get("attemptIndex", 0) <= 3:
                raise ValueError("REPAIRING progress requires attemptIndex 1..3")
            if not 1 <= self.payload.statistics.get("actionCount", 0) <= 16:
                raise ValueError("REPAIRING progress requires actionCount 1..16")
        return self


class CandidateItinerarySnapshot(ReplanItinerarySnapshot):
    provider: Literal["AMAP", "DEMO", "MIXED"]

    @model_validator(mode="after")
    def validate_activity_sources(self) -> Self:
        sources = {activity.source for day in self.days for activity in day.activities}
        if self.provider == "MIXED":
            if not sources <= {"AMAP", "DEMO"}:
                raise ValueError("candidate activity source is unsupported")
        elif sources != {self.provider}:
            raise ValueError("candidate activity source must match itinerary provider")
        return self


def wire_provider_for_snapshot(
    snapshot: CandidateItinerarySnapshot | ReplanItinerarySnapshot,
) -> str:
    """Map a persisted snapshot provider to the wire completion provider.

    'MIXED' is a Java persistence aggregate (AMAP + DEMO activities in one
    version) and is NOT a legal wire completion provider — the completion
    payload only accepts AMAP/DEMO (F5).  When the snapshot is MIXED the wire
    provider follows the activity sources (AMAP if any AMAP activity exists,
    otherwise DEMO).
    """
    if snapshot.provider != "MIXED":
        return snapshot.provider
    sources = {activity.source for day in snapshot.days for activity in day.activities}
    return "AMAP" if "AMAP" in sources else "DEMO"


class PlanningCandidateValidationPayload(InboundMessageModel):
    task_type: Literal["EDIT_VALIDATE", "ROLLBACK_VALIDATE"]
    candidate_type: Literal["EDIT", "ROLLBACK"]
    baseline_trip_version: int = Field(strict=True, ge=0)
    baseline_itinerary_version_id: UUID
    rollback_from_version_id: UUID | None = None
    idempotency_key: UUID
    changed_dates: tuple[date, ...] = Field(min_length=1, max_length=7)
    impacted_dates: tuple[date, ...] = Field(min_length=1, max_length=7)
    trip: TripSnapshot
    itinerary: CandidateItinerarySnapshot
    knowledge: KnowledgeEvidence
    planning_context: PlanningContextSnapshot | None = None

    @model_validator(mode="after")
    def validate_candidate_scope(self) -> Self:
        expected_task_type = f"{self.candidate_type}_VALIDATE"
        if self.task_type != expected_task_type:
            raise ValueError("candidateType must match taskType")
        if (self.candidate_type == "ROLLBACK") != (
            self.rollback_from_version_id is not None
        ):
            raise ValueError("rollback candidates require rollbackFromVersionId")
        if self.baseline_trip_version != self.trip.version:
            raise ValueError("baselineTripVersion must match trip.version")
        expected_dates = tuple(
            self.trip.start_date + timedelta(days=offset)
            for offset in range((self.trip.end_date - self.trip.start_date).days + 1)
        )
        if tuple(day.date for day in self.itinerary.days) != expected_dates:
            raise ValueError("candidate itinerary must contain every trip date in order")
        expected_set = set(expected_dates)
        changed = set(self.changed_dates)
        if len(changed) != len(self.changed_dates) or not changed <= expected_set:
            raise ValueError("changedDates must be unique itinerary dates")
        impacted = set(self.impacted_dates)
        if len(impacted) != len(self.impacted_dates) or not impacted <= expected_set:
            raise ValueError("impactedDates must be unique itinerary dates")
        expanded = {
            candidate
            for changed_date in changed
            for candidate in (
                changed_date - timedelta(days=1),
                changed_date,
                changed_date + timedelta(days=1),
            )
            if candidate in expected_set
        }
        if impacted != expanded:
            raise ValueError("impactedDates must be the exact N-1/N/N+1 scope")
        return self


class PlanningCandidateValidationCommand(InboundMessageModel):
    event_type: Literal["PLANNING_CANDIDATE_VALIDATION_REQUESTED"]
    schema_version: Literal[1, 2]
    event_id: UUID
    trace_id: UUID
    task_id: UUID
    trip_id: UUID
    occurred_at: datetime
    payload: PlanningCandidateValidationPayload

    @model_validator(mode="before")
    @classmethod
    def require_raw_technical_route_modes(cls, value: object) -> object:
        return _forbid_raw_taxi_on_wire(value)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurredAt must include a timezone")
        if self.schema_version == 2:
            # B13_FIX R1: v2 snapshots always carry the boundary fields.
            snapshot = self.payload.trip
            if "arrival_at" not in snapshot.model_fields_set:
                raise ValueError("schemaVersion 2 requires snapshot arrivalAt")
            if "departure_at" not in snapshot.model_fields_set:
                raise ValueError("schemaVersion 2 requires snapshot departureAt")
            _forbid_taxi_on_v2_wire(self.payload.itinerary)
        context = self.payload.planning_context
        if context is not None and (
            context.trip_id != self.trip_id
            or context.planning_task_id != self.task_id
            or context.city != self.payload.trip.destination
            or context.travel_start_date != self.payload.trip.start_date
            or context.travel_end_date != self.payload.trip.end_date
            or context.generated_at > self.occurred_at
        ):
            raise ValueError("planning context identity must match the command")
        return self


AgentExpectedType = Literal["TEXT", "NUMBER", "DATE", "CHOICE"]
# "at least one non-whitespace character" — mirrors the Java parsers' isBlank
# rejection so both sides enforce the same question/option/answer rule.
AgentOptionText = Annotated[str, StringConstraints(min_length=1, max_length=60, pattern=r"\S")]
AgentQuestionText = Annotated[str, StringConstraints(min_length=1, max_length=300, pattern=r"\S")]
AgentAnswerText = Annotated[str, StringConstraints(min_length=1, max_length=2000, pattern=r"\S")]


class AgentAskUserPayload(MessageModel):
    """What the agent needs from the human before the loop can continue."""

    question: AgentQuestionText
    options: tuple[AgentOptionText, ...] | None = Field(default=None, max_length=10)
    expected_type: AgentExpectedType | None = None


class AgentAskUserEvent(MessageModel):
    """AGENT_ASK_USER v1: the loop stopped in WAITING_USER and needs an answer.

    Published on the event exchange.  The user's verbatim answer returns as an
    AGENT_RESUME command whose eventId is that resume's idempotency key.
    """

    event_type: Literal["AGENT_ASK_USER"]
    schema_version: Literal[1]
    event_id: UUID
    trace_id: UUID
    trip_id: UUID
    run_id: UUID
    occurred_at: datetime
    payload: AgentAskUserPayload

    @model_validator(mode="after")
    def validate_occurred_at(self) -> Self:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurredAt must include a timezone")
        return self


class AgentResumePayload(InboundMessageModel):
    """The user's verbatim words — they double as slot evidence."""

    answer: AgentAnswerText


class AgentResumeCommand(InboundMessageModel):
    """AGENT_RESUME v1: continue a WAITING_USER run with the user's answer."""

    event_type: Literal["AGENT_RESUME"]
    schema_version: Literal[1]
    event_id: UUID
    trace_id: UUID
    trip_id: UUID
    run_id: UUID
    occurred_at: datetime
    payload: AgentResumePayload

    @model_validator(mode="after")
    def validate_occurred_at(self) -> Self:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurredAt must include a timezone")
        return self


AgentMessageText = Annotated[
    str, StringConstraints(min_length=1, max_length=2000, pattern=r"\S")
]


class AgentStartPayload(InboundMessageModel):
    """The user's opening utterance — the loop's evidence source.

    ``trip_context`` carries the trip entity's destination/dates as read-only
    TRIP facts so the worker seeds the dialog instead of re-asking what the
    user already set during the creation flow.
    """

    message: AgentMessageText
    trip_context: dict[str, str] | None = Field(default=None, alias="tripContext")


class AgentStartCommand(InboundMessageModel):
    """AGENT_START v1: open a dialog turn; the worker creates the run.

    The envelope carries no runId because the run does not exist yet — the
    worker generates it and echoes it back on the AGENT_ASK_USER event.
    ``userId`` is optional (additive extension for P3.2 profile memory): the
    cross-session profile is keyed by it when present.
    """

    event_type: Literal["AGENT_START"]
    schema_version: Literal[1]
    event_id: UUID
    trace_id: UUID
    trip_id: UUID
    user_id: UUID | None = None
    occurred_at: datetime
    payload: AgentStartPayload

    @model_validator(mode="after")
    def validate_occurred_at(self) -> Self:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurredAt must include a timezone")
        return self


AgentToolName = Annotated[str, StringConstraints(min_length=1, max_length=60)]
AgentSummaryText = Annotated[
    str, StringConstraints(min_length=1, max_length=300, pattern=r"\S")
]
AgentErrorCode = Annotated[str, StringConstraints(min_length=1, max_length=60)]


class AgentStepPayload(MessageModel):
    """One restrained tool-step trace entry (P2.7 克制版).

    ``seq`` counts tool steps within the current dialog turn, from zero.
    Decision ("thinking") detail deliberately stays in the trajectory API —
    the frontend progress signal is the tool steps themselves.
    """

    seq: int = Field(strict=True, ge=0)
    tool: AgentToolName
    ok: bool
    summary: AgentSummaryText
    error_code: AgentErrorCode | None = None


class AgentStepEvent(MessageModel):
    """AGENT_STEP v1: a tool step the backend may stream to the frontend."""

    event_type: Literal["AGENT_STEP"]
    schema_version: Literal[1]
    event_id: UUID
    trace_id: UUID
    trip_id: UUID
    run_id: UUID
    occurred_at: datetime
    payload: AgentStepPayload

    @model_validator(mode="after")
    def validate_occurred_at(self) -> Self:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurredAt must include a timezone")
        return self


class AgentSlotView(MessageModel):
    """One confirmed-slot projection entry riding the completed event (P2.8b)."""

    value: Any = None
    state: str


class AgentCompletedPayload(MessageModel):
    """AGENT_COMPLETED 事件载荷（AUDIT-01 归边后，不再携带完整 itinerary）。

    Agent 对话框链只声明「对话语义」：一段人类可读摘要 + 已确认槽位投影。
    权威行程由 Planner 管线生成并通过 PLANNING_COMPLETED 落库；此事件若再
    携带 itinerary.days 会与管线形成两套权威行程，属审计发现的冗余/分叉。
    """

    summary: AgentSummaryText
    slots: dict[str, AgentSlotView] | None = None


class AgentCompletedEvent(MessageModel):
    """AGENT_COMPLETED v1: the loop emitted a validated itinerary."""

    event_type: Literal["AGENT_COMPLETED"]
    schema_version: Literal[1]
    event_id: UUID
    trace_id: UUID
    trip_id: UUID
    run_id: UUID
    occurred_at: datetime
    payload: AgentCompletedPayload

    @model_validator(mode="after")
    def validate_occurred_at(self) -> Self:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurredAt must include a timezone")
        return self


AgentRunFinishedStatus = Literal["STOPPED", "FAILED", "EXPIRED", "ANSWERED"]


class AgentRunFinishedPayload(MessageModel):
    """Why a run ended without a question or an itinerary (P0 终态可见性).

    Every terminal that is neither WAITING_USER nor EMITTED used to be
    invisible to the frontend (ceiling reached, expired wait, rejected
    resume, plain text answer) — the user saw a spinner forever.  This event
    closes each of those paths; ``message`` is already user-safe copy.
    """

    status: AgentRunFinishedStatus
    reason_code: AgentErrorCode
    message: AgentSummaryText


class AgentRunFinishedEvent(MessageModel):
    """AGENT_RUN_FINISHED v1: the run reached a terminal the user must see."""

    event_type: Literal["AGENT_RUN_FINISHED"]
    schema_version: Literal[1]
    event_id: UUID
    trace_id: UUID
    trip_id: UUID
    run_id: UUID
    occurred_at: datetime
    payload: AgentRunFinishedPayload

    @model_validator(mode="after")
    def validate_occurred_at(self) -> Self:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurredAt must include a timezone")
        return self
