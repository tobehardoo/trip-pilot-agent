"""Planning domain protocols and core value objects.

Extracted from ``worker/processor.py`` so that provider implementations
and application orchestrators can depend on the domain layer without
importing the entire worker module.
"""

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID

from trip_agent.providers.errors import PlanningProviderError  # noqa: F401
from trip_agent.providers.map import MapProviderName, Poi
from trip_agent.worker.contracts import (
    FallbackOperation,
    Itinerary,
    KnowledgeEvidence,
    PlanningCreateCommand,
    PlanningReplanCommand,
    ProviderProvenance,
)

if TYPE_CHECKING:
    from trip_agent.feasibility.inputs import ValidationInputs
    from trip_agent.planning.trip_skeleton import TripSkeleton


@dataclass(frozen=True, slots=True)
class OptimizationConflict:
    code: Literal[
        "FIXED_SCHEDULE_OVERLAP",
        "INSUFFICIENT_DAY_CAPACITY",
        "BUDGET_EXCEEDED",
        "MUST_VISIT_UNAVAILABLE",
        "MOBILITY_ROUTE_TOO_LONG",
        "TRAVEL_ANCHOR_UNAVAILABLE",
        "MUST_VISIT_UNVERIFIABLE_IN_DEMO",
    ]
    message: str
    affected: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelaxationSuggestion:
    code: Literal[
        "CHANGE_FIXED_SCHEDULE",
        "REDUCE_OPTIONAL_ACTIVITIES",
        "EXTEND_AVAILABLE_TIME",
        "INCREASE_BUDGET",
        "CHANGE_MOBILITY_OR_TRANSPORT",
        "CHECK_TRAVEL_ANCHOR",
        "RETRY_REAL_PROVIDER",
        "ADJUST_TRAVEL_CONTEXT",
    ]
    message: str


class PlanningProvider(Protocol):
    """A provider that can generate a complete trip itinerary.

    Implementations may use external maps, knowledge retrieval, and
    constraint optimisation.  The protocol keeps application code
    independent of any single provider implementation.
    """

    async def plan(self, command: PlanningCreateCommand) -> "PlanningResult": ...

    async def replan(self, command: PlanningReplanCommand) -> "PlanningResult": ...

    async def repair(self, request: "PlanningRepairRequest") -> "PlanningResult": ...


class KnowledgeEvidenceProvider(Protocol):
    """Sources used by the planning pipeline to explain recommendations."""

    async def get_evidence(
        self, command: PlanningCreateCommand
    ) -> KnowledgeEvidence: ...


@dataclass(frozen=True)
class PlanningResult:
    """Immutable result of a planning or replanning invocation."""

    provider: MapProviderName
    itinerary: Itinerary
    guide_fact_ids: tuple[UUID, ...] = ()
    requested_provider_mode: str | None = None
    primary_provider: str | None = None
    actual_providers: tuple[str, ...] = ()
    fallback_attempted: bool = False
    fallback_succeeded: bool = False
    fallback_reason: str | None = None
    fallback_operations: tuple[FallbackOperation, ...] = ()
    evaluation: object | None = None  # PlanEvaluation — lazy import to avoid cycle
    # Transient planning-only aggregate consumed by hard validation and
    # bounded repair. It never enters messaging, persistence, or API surfaces.
    trip_skeleton: "TripSkeleton | None" = None
    # Transient opening/duration/meal inputs consumed by hard validation and
    # bounded repair. Messaging, DB, and API expose only the resulting report.
    validation_inputs: "ValidationInputs | None" = None

    def provider_provenance(self) -> ProviderProvenance | None:
        if self.requested_provider_mode is None:
            if (
                self.primary_provider is not None
                or self.actual_providers
                or self.fallback_attempted
                or self.fallback_succeeded
                or self.fallback_reason is not None
                or self.fallback_operations
            ):
                raise ValueError("partial provider provenance is not publishable")
            return None
        return ProviderProvenance(
            requested_provider_mode=self.requested_provider_mode,
            primary_provider=self.primary_provider,
            actual_providers=self.actual_providers,
            fallback_attempted=self.fallback_attempted,
            fallback_succeeded=self.fallback_succeeded,
            fallback_reason=self.fallback_reason,
            fallback_operations=self.fallback_operations,
        )


@dataclass(frozen=True, slots=True)
class PlanningRepairRequest:
    """One bounded provider refresh for a locally repaired candidate."""

    command: PlanningCreateCommand | PlanningReplanCommand
    candidate: PlanningResult
    impacted_dates: tuple[date, ...]
    attempt_index: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "impacted_dates", tuple(self.impacted_dates))
        if not 1 <= self.attempt_index <= 3:
            raise ValueError("repair attempt_index must be between one and three")
        if not self.impacted_dates or len(self.impacted_dates) > 3:
            raise ValueError("repair must cover between one and three dates")
        if tuple(sorted(set(self.impacted_dates))) != self.impacted_dates:
            raise ValueError("repair dates must be unique and sorted")
        itinerary_dates = {day.date for day in self.candidate.itinerary.days}
        if any(day not in itinerary_dates for day in self.impacted_dates):
            raise ValueError("repair dates must belong to the candidate itinerary")


@dataclass(frozen=True)
class ResolvedTravelAnchors:
    """POIs resolved for arrival, departure, and accommodation locations."""

    arrival: Poi | None = None
    departure: Poi | None = None
    accommodation: Poi | None = None


class PlanningInfeasibleError(Exception):
    """Hard constraints cannot be satisfied and must be shown to the user."""

    def __init__(
        self,
        conflicts: tuple[OptimizationConflict, ...],
        relaxations: tuple[RelaxationSuggestion, ...],
    ) -> None:
        super().__init__(
            conflicts[0].message if conflicts else "No feasible itinerary"
        )
        self.conflicts = conflicts
        self.relaxations = relaxations
