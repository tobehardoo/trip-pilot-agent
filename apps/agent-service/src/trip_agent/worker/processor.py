"""Planning command processing — application orchestrators.

After Phase 2 extraction this module retains only the top‑level process
functions and backward‑compatible re‑exports.  Provider implementations
live in ``infrastructure/``, domain protocols in ``domain/planning/``,
and workflow composition in ``workflow/``.
"""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from trip_agent.application.replan_service import LocalReplanningProvider  # noqa: F811
from trip_agent.domain.planning.protocols import (
    KnowledgeEvidenceProvider,
    PlanningInfeasibleError,
    PlanningProvider,
    PlanningProviderError,
    PlanningResult,
    ResolvedTravelAnchors,
)

# Re‑exports for backward compatibility — the canonical definitions live in
# domain/shared.py and domain/planning/protocols.py.
from trip_agent.domain.shared import (  # noqa: F401
    AMAP_ACTIVITY_ESTIMATED_COST,
    CHINA_TIME_ZONE,
    COORDINATE_SCALE,
    DEFAULT_POI_KEYWORDS,
    MAX_PAIR_ATTEMPTS_PER_PLAN,
    MAX_PLANNING_CANDIDATES,
    MAX_POI_QUERIES,
    MAX_ROUTE_CALLS_PER_PLAN,
    MAX_TRIP_DAYS,
    text_matches,
)
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider  # noqa: F811
from trip_agent.infrastructure.demo.knowledge_provider import (
    DemoKnowledgeEvidenceProvider,  # noqa: F811
)
from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider  # noqa: F811
from trip_agent.worker.contracts import (
    KnowledgeCitationSnapshot,
    KnowledgeEvidence,
    KnowledgeFreshness,
    PlanningCompletedEvent,
    PlanningCompletedPayload,
    PlanningConflict,
    PlanningCreateCommand,
    PlanningFailedEvent,
    PlanningFailedPayload,
    PlanningRelaxation,
    PlanningReplanCommand,
)
from trip_agent.workflow.planner_pipeline import FallbackPlanningProvider  # noqa: F811

__all__ = [
    "AMAP_ACTIVITY_ESTIMATED_COST",
    "COORDINATE_SCALE",
    "DEFAULT_POI_KEYWORDS",
    "MAX_PAIR_ATTEMPTS_PER_PLAN",
    "MAX_PLANNING_CANDIDATES",
    "MAX_POI_QUERIES",
    "MAX_ROUTE_CALLS_PER_PLAN",
    "MAX_TRIP_DAYS",
    "AmapPlanningProvider",
    "DemoKnowledgeEvidenceProvider",
    "DemoPlanningProvider",
    "FallbackPlanningProvider",
    "KnowledgeEvidenceProvider",
    "LocalReplanningProvider",
    "PlanningInfeasibleError",
    "PlanningProvider",
    "PlanningProviderError",
    "PlanningResult",
    "ResolvedTravelAnchors",
    "planning_failed_event",
    "process_planning_create",
    "process_planning_replan",
]


async def process_planning_create(
    command: PlanningCreateCommand,
    provider: PlanningProvider,
    *,
    knowledge_provider: KnowledgeEvidenceProvider | None = None,
    occurred_at: datetime | None = None,
) -> PlanningCompletedEvent:
    completed_at = occurred_at or datetime.now(UTC)
    effective_command = _command_with_fresh_guide_evidence(command, completed_at)
    result = await provider.plan(effective_command)
    knowledge = await (knowledge_provider or DemoKnowledgeEvidenceProvider()).get_evidence(
        effective_command
    )
    knowledge = _merge_guide_evidence(
        effective_command,
        result,
        knowledge,
        checked_at=completed_at,
    )
    return PlanningCompletedEvent(
        event_type="PLANNING_COMPLETED",
        schema_version=5,
        event_id=_completed_event_id(command.event_id),
        trace_id=command.trace_id,
        task_id=command.task_id,
        trip_id=command.trip_id,
        run_id=_run_id(command.task_id),
        occurred_at=completed_at,
        payload=PlanningCompletedPayload(
            provider=result.provider,
            itinerary=result.itinerary,
            knowledge=knowledge,
        ),
    )


async def process_planning_replan(
    command: PlanningReplanCommand,
    provider: PlanningProvider,
    *,
    occurred_at: datetime | None = None,
) -> PlanningCompletedEvent:
    completed_at = occurred_at or datetime.now(UTC)
    result = await provider.replan(command)
    return PlanningCompletedEvent(
        event_type="PLANNING_COMPLETED",
        schema_version=5,
        event_id=_completed_event_id(command.event_id),
        trace_id=command.trace_id,
        task_id=command.task_id,
        trip_id=command.trip_id,
        run_id=_run_id(command.task_id),
        occurred_at=completed_at,
        payload=PlanningCompletedPayload(
            provider=result.provider,
            itinerary=result.itinerary,
            knowledge=command.payload.knowledge,
        ),
    )


def _command_with_fresh_guide_evidence(
    command: PlanningCreateCommand,
    checked_at: datetime,
) -> PlanningCreateCommand:
    fresh_facts = tuple(
        fact
        for fact in command.payload.guide_evidence.facts
        if fact.observed_at <= checked_at < fact.expires_at
    )
    if len(fresh_facts) == len(command.payload.guide_evidence.facts):
        return command
    guide_evidence = command.payload.guide_evidence.model_copy(update={"facts": fresh_facts})
    payload = command.payload.model_copy(update={"guide_evidence": guide_evidence})
    return command.model_copy(update={"payload": payload})


def planning_failed_event(
    command: PlanningCreateCommand | PlanningReplanCommand,
    failure: PlanningInfeasibleError,
    *,
    occurred_at: datetime | None = None,
) -> PlanningFailedEvent:
    return PlanningFailedEvent(
        event_type="PLANNING_FAILED",
        schema_version=1,
        event_id=_failed_event_id(command.event_id),
        trace_id=command.trace_id,
        task_id=command.task_id,
        trip_id=command.trip_id,
        run_id=_run_id(command.task_id),
        occurred_at=occurred_at or datetime.now(UTC),
        payload=PlanningFailedPayload(
            status="FAILED",
            error_code="NO_FEASIBLE_ITINERARY",
            message=str(failure),
            conflicts=tuple(
                PlanningConflict(
                    code=item.code,
                    message=item.message,
                    affected=item.affected,
                )
                for item in failure.conflicts
            ),
            relaxation_suggestions=tuple(
                PlanningRelaxation(code=item.code, message=item.message)
                for item in failure.relaxations
            ),
        ),
    )


def _completed_event_id(command_event_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"trip-pilot/planning-completed/{command_event_id}")


def _failed_event_id(command_event_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"trip-pilot/planning-failed/{command_event_id}")


def _run_id(task_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"trip-pilot/agent-run/{task_id}")


# (coordinate_decimal, amap_activity, candidate_keywords, matched_guide_fact_ids
#  moved to domain/shared.py)


def _merge_guide_evidence(
    command: PlanningCreateCommand,
    result: PlanningResult,
    knowledge: KnowledgeEvidence,
    *,
    checked_at: datetime,
) -> KnowledgeEvidence:
    used_ids = set(result.guide_fact_ids)
    facts = tuple(fact for fact in command.payload.guide_evidence.facts if fact.fact_id in used_ids)
    if not facts:
        return knowledge
    guide_citations = tuple(
        KnowledgeCitationSnapshot(
            document_id=str(fact.guide_import_id),
            document_version=1,
            chunk_id=str(fact.fact_id),
            chunk_index=index,
            title=f"{fact.source_title}｜{fact.statement}"[:200],
            source_url=fact.source_url,
            source_name=fact.source_host[:120],
            collected_at=fact.observed_at,
            reliability_level=(
                "provider-live"
                if fact.source_type == "CITY_INTELLIGENCE"
                else "community-guide"
            ),
            similarity=fact.confidence,
        )
        for index, fact in enumerate(facts)
    )
    citations = (
        (*guide_citations, *knowledge.citations) if knowledge.status == "REAL" else guide_citations
    )[:20]
    freshness = (
        knowledge.freshness
        if knowledge.status == "REAL"
        else KnowledgeFreshness(status="FRESH", checked_at=checked_at)
    )
    return KnowledgeEvidence(
        status="REAL",
        query=knowledge.query,
        citations=citations,
        freshness=freshness,
    )
