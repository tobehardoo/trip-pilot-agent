"""Planning domain protocols and core value objects.

Extracted from ``worker/processor.py`` so that provider implementations
and application orchestrators can depend on the domain layer without
importing the entire worker module.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from trip_agent.planning.optimization import OptimizationConflict, RelaxationSuggestion
from trip_agent.providers.map import MapProviderName, Poi
from trip_agent.worker.contracts import (
    Itinerary,
    KnowledgeEvidence,
    PlanningCreateCommand,
    PlanningReplanCommand,
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


@dataclass(frozen=True)
class ResolvedTravelAnchors:
    """POIs resolved for arrival, departure, and accommodation locations."""

    arrival: Poi | None = None
    departure: Poi | None = None
    accommodation: Poi | None = None


class PlanningProviderError(Exception):
    """An expected provider failure that may use the configured fallback."""


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
