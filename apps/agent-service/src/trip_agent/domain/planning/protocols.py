"""Planning domain protocols and core value objects.

Extracted from ``worker/processor.py`` so that provider implementations
and application orchestrators can depend on the domain layer without
importing the entire worker module.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from trip_agent.planning.optimization import OptimizationConflict, RelaxationSuggestion
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


class PlanningProvider(Protocol):
    """A provider that can generate a complete trip itinerary.

    Implementations may use external maps, knowledge retrieval, and
    constraint optimisation.  The protocol keeps application code
    independent of any single provider implementation.
    """

    async def plan(self, command: PlanningCreateCommand) -> "PlanningResult": ...

    async def replan(self, command: PlanningReplanCommand) -> "PlanningResult": ...


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
