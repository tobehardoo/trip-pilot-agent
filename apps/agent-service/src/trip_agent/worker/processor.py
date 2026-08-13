"""Planning command processing — application orchestrators.

After Phase 2 extraction this module retains only the top‑level process
functions and backward‑compatible re‑exports.  Provider implementations
live in ``infrastructure/``, domain protocols in ``domain/planning/``,
and workflow composition in ``workflow/``.
"""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from trip_agent.application.candidate_validation import CandidateValidationProvider
from trip_agent.application.replan_service import LocalReplanningProvider  # noqa: F811
from trip_agent.domain.planning.protocols import (
    KnowledgeEvidenceProvider,
    PlanningInfeasibleError,
    PlanningProvider,
    PlanningProviderError,
    PlanningRepairRequest,
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
    MAX_POI_QUERIES,
    MAX_ROUTE_CALLS_PER_PLAN,
    MAX_TRIP_DAYS,
    text_matches,
)
from trip_agent.evaluation import get_plan_evaluator
from trip_agent.feasibility.repair.engine import apply_repair_plan, plan_repairs
from trip_agent.feasibility.repair.session import (
    advance_repair_session,
    start_repair_session,
)
from trip_agent.feasibility.validator import ValidationRun, run_validation
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider  # noqa: F811
from trip_agent.infrastructure.demo.knowledge_provider import (
    DemoKnowledgeEvidenceProvider,  # noqa: F811
)
from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider  # noqa: F811
from trip_agent.planning.trusted_context import planning_fact_impacts
from trip_agent.providers.errors import (
    ProviderErrorCategory,
    ProviderFailureDetails,
    ProviderOperation,
)
from trip_agent.worker.contracts import (
    KnowledgeCitationSnapshot,
    KnowledgeEvidence,
    KnowledgeFreshness,
    PlanningCandidateValidationCommand,
    PlanningCompletedEventV9,
    PlanningCompletedPayloadV9,
    PlanningConflict,
    PlanningCreateCommand,
    PlanningFactImpact,
    PlanningFailedEvent,
    PlanningFailedPayload,
    PlanningRelaxation,
    PlanningReplanCommand,
    PlanningReviewRequiredEvent,
    PlanningReviewRequiredPayload,
)
from trip_agent.worker.progress import report_planning_progress
from trip_agent.worker.structured_logging import planning_logger
from trip_agent.workflow.planner_pipeline import FallbackPlanningProvider  # noqa: F811

__all__ = [
    "AMAP_ACTIVITY_ESTIMATED_COST",
    "COORDINATE_SCALE",
    "DEFAULT_POI_KEYWORDS",
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
    "process_candidate_validation",
    "process_planning_replan",
]


async def process_planning_create(
    command: PlanningCreateCommand,
    provider: PlanningProvider,
    *,
    knowledge_provider: KnowledgeEvidenceProvider | None = None,
    occurred_at: datetime | None = None,
) -> PlanningCompletedEventV9 | PlanningReviewRequiredEvent:
    completed_at = occurred_at or datetime.now(UTC)
    log = planning_logger(
        "trip_agent.worker.processor",
        trace_id=str(command.trace_id),
        event_id=str(command.event_id),
        task_id=str(command.task_id),
        trip_id=str(command.trip_id),
        task_type="CREATE",
    )
    log.info("command received: PLANNING_CREATE")
    await report_planning_progress(
        "CONTEXT_VALIDATING",
        "Validating the planning context and constraints",
    )
    effective_command = _command_with_fresh_guide_evidence(command, completed_at)
    await report_planning_progress(
        "CITY_FACTS_LOADING",
        "Loading current city facts and guide evidence",
        {"guideFactCount": len(effective_command.payload.guide_evidence.facts)},
    )
    log.info("provider started", extra={"provider": "PLANNING"})
    result = await provider.plan(effective_command)
    log.info("provider completed", extra={"provider": result.provider})
    # B6: authoritative feasibility gate.  The report is derived from the
    # same itinerary that will be emitted; validated_at is the caller-owned
    # timestamp and the report id is a deterministic uuid5 of the command.
    validation = run_validation(
        command=effective_command,
        itinerary=result.itinerary,
        report_id=_feasibility_report_id(command.event_id),
        validated_at=completed_at,
        trip_skeleton=result.trip_skeleton,
        validation_inputs=result.validation_inputs,
    )
    log.info(
        "validation result: %s",
        validation.report.status.value,
        extra={"outcome_status": validation.report.status.value},
    )
    result, validation = await _repair_if_needed(
        effective_command,
        provider,
        result,
        validation,
        log=log,
    )
    await report_planning_progress(
        "KNOWLEDGE_RETRIEVING",
        "Retrieving supporting travel knowledge",
    )
    knowledge = await (knowledge_provider or DemoKnowledgeEvidenceProvider()).get_evidence(
        effective_command
    )
    await report_planning_progress(
        "RESULT_EXPLAINING",
        "Preparing evidence and explanations for the itinerary",
    )
    knowledge = _merge_guide_evidence(
        effective_command,
        result,
        knowledge,
        checked_at=completed_at,
    )
    report = validation.report
    if report.status.value == "VERIFIED":
        evaluation = get_plan_evaluator().evaluate(effective_command, result)
        log.info("outcome emitted: PLANNING_COMPLETED", extra={"outcome_status": "VERIFIED"})
        return PlanningCompletedEventV9(
            event_type="PLANNING_COMPLETED",
            schema_version=9,
            event_id=_completed_event_id(command.event_id),
            trace_id=command.trace_id,
            task_id=command.task_id,
            trip_id=command.trip_id,
            run_id=_run_id(command.task_id),
            occurred_at=completed_at,
            payload=PlanningCompletedPayloadV9(
                provider=result.provider,
                itinerary=result.itinerary,
                knowledge=knowledge,
                fact_impacts=_fact_impacts(effective_command, result),
                provider_provenance=result.provider_provenance(),
                evaluation=evaluation,
                feasibility_report=report,
            ),
        )
    log.info("outcome emitted: PLANNING_REVIEW_REQUIRED", extra={"outcome_status": "WAITING_USER"})
    return PlanningReviewRequiredEvent(
        event_type="PLANNING_REVIEW_REQUIRED",
        schema_version=1,
        event_id=_completed_event_id(command.event_id),
        trace_id=command.trace_id,
        task_id=command.task_id,
        trip_id=command.trip_id,
        run_id=_run_id(command.task_id),
        occurred_at=completed_at,
        payload=PlanningReviewRequiredPayload(
            status="WAITING_USER",
            provider=result.provider,
            itinerary=result.itinerary,
            knowledge=knowledge,
            fact_impacts=_fact_impacts(effective_command, result),
            provider_provenance=result.provider_provenance(),
            feasibility_report=report,
        ),
    )


async def process_planning_replan(
    command: PlanningReplanCommand,
    provider: PlanningProvider,
    *,
    occurred_at: datetime | None = None,
) -> PlanningCompletedEventV9 | PlanningReviewRequiredEvent:
    completed_at = occurred_at or datetime.now(UTC)
    log = planning_logger(
        "trip_agent.worker.processor",
        trace_id=str(command.trace_id),
        event_id=str(command.event_id),
        task_id=str(command.task_id),
        trip_id=str(command.trip_id),
        task_type="REPLAN",
    )
    log.info("command received: PLANNING_REPLAN")
    await report_planning_progress(
        "CONTEXT_VALIDATING",
        "Validating the local replanning scope",
        {"impactedDays": len(command.payload.impacted_dates)},
    )
    log.info("provider started", extra={"provider": "REPLAN"})
    result = await provider.replan(command)
    log.info("provider completed", extra={"provider": result.provider})
    validation = run_validation(
        command=command,
        itinerary=result.itinerary,
        report_id=_feasibility_report_id(command.event_id),
        validated_at=completed_at,
        trip_skeleton=result.trip_skeleton,
        validation_inputs=result.validation_inputs,
    )
    log.info(
        "validation result: %s",
        validation.report.status.value,
        extra={"outcome_status": validation.report.status.value},
    )
    result, validation = await _repair_if_needed(
        command,
        provider,
        result,
        validation,
        log=log,
    )
    await report_planning_progress(
        "RESULT_EXPLAINING",
        "Preparing the updated local itinerary",
    )
    report = validation.report
    if report.status.value == "VERIFIED":
        evaluation = get_plan_evaluator().evaluate(command, result)
        log.info("outcome emitted: PLANNING_COMPLETED", extra={"outcome_status": "VERIFIED"})
        return PlanningCompletedEventV9(
            event_type="PLANNING_COMPLETED",
            schema_version=9,
            event_id=_completed_event_id(command.event_id),
            trace_id=command.trace_id,
            task_id=command.task_id,
            trip_id=command.trip_id,
            run_id=_run_id(command.task_id),
            occurred_at=completed_at,
            payload=PlanningCompletedPayloadV9(
                provider=result.provider,
                itinerary=result.itinerary,
                knowledge=command.payload.knowledge,
                fact_impacts=(),
                provider_provenance=result.provider_provenance(),
                evaluation=evaluation,
                feasibility_report=report,
            ),
        )
    log.info("outcome emitted: PLANNING_REVIEW_REQUIRED", extra={"outcome_status": "WAITING_USER"})
    return PlanningReviewRequiredEvent(
        event_type="PLANNING_REVIEW_REQUIRED",
        schema_version=1,
        event_id=_completed_event_id(command.event_id),
        trace_id=command.trace_id,
        task_id=command.task_id,
        trip_id=command.trip_id,
        run_id=_run_id(command.task_id),
        occurred_at=completed_at,
        payload=PlanningReviewRequiredPayload(
            status="WAITING_USER",
            provider=result.provider,
            itinerary=result.itinerary,
            knowledge=command.payload.knowledge,
            fact_impacts=(),
            provider_provenance=result.provider_provenance(),
            feasibility_report=report,
        ),
    )


async def process_candidate_validation(
    command: PlanningCandidateValidationCommand,
    provider: CandidateValidationProvider,
    *,
    occurred_at: datetime | None = None,
) -> PlanningCompletedEventV9 | PlanningReviewRequiredEvent:
    completed_at = occurred_at or datetime.now(UTC)
    log = planning_logger(
        "trip_agent.worker.processor",
        trace_id=str(command.trace_id),
        event_id=str(command.event_id),
        task_id=str(command.task_id),
        trip_id=str(command.trip_id),
        task_type=command.payload.task_type,
        candidate_type=command.payload.candidate_type,
    )
    log.info("command received: PLANNING_CANDIDATE_VALIDATION")
    await report_planning_progress(
        "CONTEXT_VALIDATING",
        "Validating an immutable edit or rollback candidate",
        {"impactedDays": len(command.payload.impacted_dates)},
    )
    log.info("provider started", extra={"provider": "CANDIDATE_VALIDATION"})
    result = await provider.validate(command)
    log.info("provider completed", extra={"provider": result.provider})
    validation = run_validation(
        command=command,
        itinerary=result.itinerary,
        report_id=_feasibility_report_id(command.event_id),
        validated_at=completed_at,
        trip_skeleton=result.trip_skeleton,
        validation_inputs=result.validation_inputs,
    )
    log.info(
        "validation result: %s",
        validation.report.status.value,
        extra={"outcome_status": validation.report.status.value},
    )
    result, validation = await _repair_if_needed(command, provider, result, validation, log=log)
    report = validation.report
    common = {
        "provider": result.provider,
        "itinerary": result.itinerary,
        "knowledge": command.payload.knowledge,
        "fact_impacts": _candidate_fact_impacts(command, result),
        "provider_provenance": result.provider_provenance(),
        "feasibility_report": report,
    }
    if report.status.value == "VERIFIED":
        log.info("outcome emitted: PLANNING_COMPLETED", extra={"outcome_status": "VERIFIED"})
        return PlanningCompletedEventV9(
            event_type="PLANNING_COMPLETED",
            schema_version=9,
            event_id=_completed_event_id(command.event_id),
            trace_id=command.trace_id,
            task_id=command.task_id,
            trip_id=command.trip_id,
            run_id=_run_id(command.task_id),
            occurred_at=completed_at,
            payload=PlanningCompletedPayloadV9(
                **common,
                evaluation=get_plan_evaluator().evaluate(command, result),
            ),
        )
    log.info("outcome emitted: PLANNING_REVIEW_REQUIRED", extra={"outcome_status": "WAITING_USER"})
    return PlanningReviewRequiredEvent(
        event_type="PLANNING_REVIEW_REQUIRED",
        schema_version=1,
        event_id=_completed_event_id(command.event_id),
        trace_id=command.trace_id,
        task_id=command.task_id,
        trip_id=command.trip_id,
        run_id=_run_id(command.task_id),
        occurred_at=completed_at,
        payload=PlanningReviewRequiredPayload(status="WAITING_USER", **common),
    )


async def _repair_if_needed(
    command: PlanningCreateCommand | PlanningReplanCommand | PlanningCandidateValidationCommand,
    provider: PlanningProvider | CandidateValidationProvider,
    result: PlanningResult,
    validation: ValidationRun,
    *,
    log: Any = None,
) -> tuple[PlanningResult, ValidationRun]:
    session = start_repair_session(validation)
    candidate = result
    while session.stop_reason is None:
        attempt_index = len(session.attempts) + 1
        plan = plan_repairs(session.current, attempt_index=attempt_index)
        if plan is None:
            break
        if log is not None:
            log.info(
                "repair attempt started",
                extra={"attempt_index": attempt_index},
            )
        await report_planning_progress(
            "REPAIRING",
            "Applying a bounded feasibility repair",
            {
                "attemptIndex": attempt_index,
                "actionCount": len(plan.actions),
            },
        )
        applied = apply_repair_plan(session.current, plan)
        candidate = _planning_result_with_candidate(candidate, applied.candidate)
        if applied.provider_dates:
            candidate = await provider.repair(
                PlanningRepairRequest(
                    command=command,
                    candidate=candidate,
                    impacted_dates=applied.provider_dates,
                    attempt_index=attempt_index,
                )
            )
        after = run_validation(
            command=command,
            itinerary=candidate.itinerary,
            report_id=session.current.report.report_id,
            validated_at=session.current.report.validated_at,
            trip_skeleton=candidate.trip_skeleton,
            validation_inputs=candidate.validation_inputs,
        )
        session = advance_repair_session(session, plan=plan, after=after)
        if log is not None:
            log.info(
                "repair attempt completed",
                extra={"attempt_index": attempt_index},
            )
    if log is not None and session.stop_reason is not None:
        log.info("repair stopped: %s", session.stop_reason)
    return candidate, session.current


def _planning_result_with_candidate(result, candidate) -> PlanningResult:
    return PlanningResult(
        provider=result.provider,
        itinerary=candidate.itinerary,
        guide_fact_ids=result.guide_fact_ids,
        requested_provider_mode=result.requested_provider_mode,
        primary_provider=result.primary_provider,
        actual_providers=result.actual_providers,
        fallback_attempted=result.fallback_attempted,
        fallback_succeeded=result.fallback_succeeded,
        fallback_reason=result.fallback_reason,
        fallback_operations=result.fallback_operations,
        trip_skeleton=candidate.trip_skeleton,
        validation_inputs=candidate.validation_inputs,
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
    command: PlanningCreateCommand | PlanningReplanCommand | PlanningCandidateValidationCommand,
    failure: PlanningInfeasibleError | PlanningProviderError | Exception,
    *,
    occurred_at: datetime | None = None,
) -> PlanningFailedEvent:
    command_operation = (
        ProviderOperation.REPLANNING
        if isinstance(command, PlanningReplanCommand)
        else ProviderOperation.PLANNING
    )
    if isinstance(failure, PlanningInfeasibleError):
        details = ProviderFailureDetails(
            category=ProviderErrorCategory.PLANNING_INFEASIBLE,
            error_code="NO_FEASIBLE_ITINERARY",
            provider="PLANNER",
            operation=command_operation,
            retryable=False,
            fallback_allowed=False,
            safe_provider_code=None,
            safe_message=str(failure),
            retry_count=0,
            cause_type=None,
        )
        conflicts = tuple(
            PlanningConflict(
                code=item.code,
                message=item.message,
                affected=item.affected,
            )
            for item in failure.conflicts
        )
        relaxations = tuple(
            PlanningRelaxation(code=item.code, message=item.message) for item in failure.relaxations
        )
    elif isinstance(failure, PlanningProviderError):
        details = failure.details
        conflicts = ()
        relaxations = ()
    else:
        details = ProviderFailureDetails(
            category=ProviderErrorCategory.INTERNAL_ERROR,
            error_code="INTERNAL_PLANNING_FAILED",
            provider="PLANNER",
            operation=command_operation,
            retryable=False,
            fallback_allowed=False,
            safe_provider_code=None,
            safe_message="Planning failed due to an internal error",
            retry_count=0,
            cause_type=type(failure).__name__,
        )
        conflicts = ()
        relaxations = ()
    return PlanningFailedEvent(
        event_type="PLANNING_FAILED",
        schema_version=2,
        event_id=_failed_event_id(command.event_id),
        trace_id=command.trace_id,
        task_id=command.task_id,
        trip_id=command.trip_id,
        run_id=_run_id(command.task_id),
        occurred_at=occurred_at or datetime.now(UTC),
        payload=PlanningFailedPayload(
            status="FAILED",
            error_code=details.error_code,
            error_category=details.category.value,
            provider=details.provider,
            operation=details.operation.value,
            retryable=details.retryable,
            retry_count=details.retry_count,
            fallback_attempted=details.fallback_attempted,
            fallback_succeeded=details.fallback_succeeded,
            safe_message=details.safe_message,
            safe_provider_code=details.safe_provider_code,
            cause_type=details.cause_type,
            conflicts=conflicts,
            relaxation_suggestions=relaxations,
        ),
    )


def _completed_event_id(command_event_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"trip-pilot/planning-completed/{command_event_id}")


def _feasibility_report_id(command_event_id: UUID) -> UUID:
    """Deterministic report id so command retries always derive the same id."""
    return uuid5(NAMESPACE_URL, f"trip-pilot/feasibility-report/{command_event_id}")


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
                "provider-live" if fact.source_type == "CITY_INTELLIGENCE" else "community-guide"
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


def _fact_impacts(
    command: PlanningCreateCommand,
    result: PlanningResult,
) -> tuple[PlanningFactImpact, ...]:
    context = command.payload.planning_context
    if context is None:
        return ()
    scheduled = tuple(
        (day.date, activity.title) for day in result.itinerary.days for activity in day.activities
    )
    return tuple(
        PlanningFactImpact.model_validate(asdict(impact))
        for impact in planning_fact_impacts(context, scheduled)
    )


def _candidate_fact_impacts(
    command: PlanningCandidateValidationCommand,
    result: PlanningResult,
) -> tuple[PlanningFactImpact, ...]:
    context = command.payload.planning_context
    if context is None:
        return ()
    scheduled = tuple(
        (day.date, activity.title) for day in result.itinerary.days for activity in day.activities
    )
    return tuple(
        PlanningFactImpact.model_validate(asdict(impact))
        for impact in planning_fact_impacts(context, scheduled)
    )
