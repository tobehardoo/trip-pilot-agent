package io.github.tobehardoo.trippilot.planning;

import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.itinerary.ItineraryService;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PlanningCompletionService implements PlanningCompletionHandler {

    private static final String SUCCEEDED = "SUCCEEDED";
    private static final String FAILED = "FAILED";

    private final PlanningTaskMapper taskMapper;
    private final PlanningTaskEventMapper taskEventMapper;
    private final ItineraryService itineraryService;
    private final PlanningFactImpactMapper factImpactMapper;
    private final io.github.tobehardoo.trippilot.itinerary.ItineraryFeasibilityReportMapper
            feasibilityReportMapper;
    private final io.github.tobehardoo.trippilot.itinerary.FeasibilityEntityRefMapper entityRefMapper;
    private final PlanningOutcomeGuard guard;
    private final ObjectMapper objectMapper;
    private final Clock clock;
    private final ApplicationEventPublisher eventPublisher;
    private final PlanningMetrics metrics;

    public PlanningCompletionService(PlanningTaskMapper taskMapper,
                                     PlanningTaskEventMapper taskEventMapper,
                                     ItineraryService itineraryService,
                                     PlanningFactImpactMapper factImpactMapper,
                                     io.github.tobehardoo.trippilot.itinerary.ItineraryFeasibilityReportMapper
                                             feasibilityReportMapper,
                                     io.github.tobehardoo.trippilot.itinerary.FeasibilityEntityRefMapper
                                             entityRefMapper,
                                     PlanningOutcomeGuard guard,
                                     ObjectMapper objectMapper,
                                     Clock clock,
                                     ApplicationEventPublisher eventPublisher,
                                     PlanningMetrics metrics) {
        this.taskMapper = taskMapper;
        this.taskEventMapper = taskEventMapper;
        this.itineraryService = itineraryService;
        this.factImpactMapper = factImpactMapper;
        this.feasibilityReportMapper = feasibilityReportMapper;
        this.entityRefMapper = entityRefMapper;
        this.guard = guard;
        this.objectMapper = objectMapper;
        this.clock = clock;
        this.eventPublisher = eventPublisher;
        this.metrics = metrics;
    }

    @Transactional
    @Override
    public void handle(PlanningCompletedEvent event) {
        // Second fail-closed gate: the parser already rejects non-v9 wire
        // events, but a caller that bypasses the parser must not be able to
        // create a formal itinerary version without a VERIFIED report.
        if (event.schemaVersion() != 9) {
            throw rejected("Only schemaVersion 9 completions can create a version");
        }
        if (event.payload() == null || event.payload().feasibilityReport() == null) {
            throw rejected("A v9 completion requires a feasibilityReport");
        }
        if (event.payload().feasibilityReport().status()
                != io.github.tobehardoo.trippilot.feasibility.FeasibilityStatus.VERIFIED) {
            throw rejected("A v9 completion requires a VERIFIED feasibilityReport");
        }
        if (event.payload().evaluation() == null) {
            throw rejected("A v9 completion requires an evaluation");
        }
        PlanningTaskCompletionRecord task = taskMapper.findCompletionContextForUpdate(event.taskId())
                .orElseThrow(() -> rejected("Planning task was not found"));
        guard.validateIdentity(event.tripId(), event.traceId(), task, "Completed event");
        var existingEvent = taskEventMapper.findByEventId(event.eventId());
        if (existingEvent.isPresent()) {
            PlanningTaskEventRecord existing = existingEvent.get();
            boolean isSameCompletedDelivery = existing.taskId().equals(task.id())
                    && ("PLANNING_COMPLETED".equals(existing.eventType())
                    || "PLANNING_FAILED".equals(existing.eventType()));
            if (isSameCompletedDelivery) {
                return;
            }
            throw rejected("Completed eventId already belongs to another planning task event");
        }
        if (!"QUEUED".equals(task.status()) && !"RUNNING".equals(task.status())) {
            throw rejected("Planning task cannot accept a completion event in status " + task.status());
        }
        guard.validateDates(event.payload().itinerary().days(), task);
        if (guard.isStaleTripBaseline(task)) {
            persistStaleFailure(event, task, "STALE_TRIP_VERSION",
                    "Trip constraints changed while planning was running");
            return;
        }
        if ("REPLAN".equals(task.taskType())) {
            if (guard.isStaleReplanBaseline(
                    task, itineraryService.getCurrentVersionForTask(task.tripId()))) {
                persistStaleFailure(event, task, "STALE_ITINERARY_VERSION",
                        "The itinerary changed while local replanning was running");
                return;
            }
            ItineraryService.CreateItineraryResult result =
                    itineraryService.createReplanVersion(
                            task.tripId(), event, task, clock);
            persistFeasibilityReportIfPresent(event, result);
            updateTaskToSucceeded(
                    event, task, result, "PLANNING_COMPLETED",
                    writeJson(completionPayload(event, result)));
            return;
        }
        ItineraryService.CreateItineraryResult result =
                itineraryService.createInitialItinerary(
                        task.tripId(), event, task.id(),
                        task.constraintSnapshotJson(), clock);
        persistFactImpacts(event, result.versionId());
        persistFeasibilityReportIfPresent(event, result);
        updateTaskToSucceeded(
                event, task, result, "PLANNING_COMPLETED",
                writeJson(completionPayload(event, result)));
    }

    /**
     * Persists the VERIFIED feasibility report of a v9 completion atomically
     * with the itinerary version and the SUCCEEDED transition.  A v9
     * completion always carries a report (enforced by the service gate), so a
     * missing report here is a programming error and must not be silently
     * tolerated.  A failed insert rolls the whole completion transaction back.
     *
     * Temporary activity/transit references inside the report are remapped to
     * the persisted node ids before storage; provider POI ids and plain text
     * references pass through unchanged.
     */
    private void persistFeasibilityReportIfPresent(
            PlanningCompletedEvent event,
            ItineraryService.CreateItineraryResult result
    ) {
        io.github.tobehardoo.trippilot.feasibility.FeasibilityReport report =
                event.payload().feasibilityReport();
        if (report == null) {
            throw new IllegalStateException("v9 completion is missing its feasibility report");
        }
        java.util.Map<java.util.UUID, java.util.UUID> activityRefs = new java.util.HashMap<>();
        for (ItineraryService.PersistedActivityReference ref : result.persistedActivities()) {
            activityRefs.put(ref.sourceActivityId(), ref.activityId());
        }
        java.util.Map<java.util.UUID, java.util.UUID> transitRefs = new java.util.HashMap<>();
        for (ItineraryService.PersistedTransitReference ref : result.persistedTransit()) {
            transitRefs.put(ref.sourceTransitId(), ref.transitId());
        }
        String reportJson = entityRefMapper.remap(writeJson(report), activityRefs, transitRefs);
        requireOne(feasibilityReportMapper.insert(
                new io.github.tobehardoo.trippilot.itinerary.ItineraryFeasibilityReportRecord(
                        result.versionId(),
                        report.reportId(),
                        report.schemaVersion(),
                        report.validatorVersion(),
                        report.itineraryFingerprint(),
                        report.status().name(),
                        report.validatedAt().toInstant(),
                        reportJson
                )
        ), "itinerary feasibility report");
    }

    private CompletionPayload completionPayload(
            PlanningCompletedEvent event,
            ItineraryService.CreateItineraryResult result
    ) {
        PlanningCompletedEvent.ProviderProvenance provenance =
                event.payload().providerProvenance();
        if (provenance == null) {
            return new CompletionPayload(
                    SUCCEEDED, event.runId(), result.versionId(),
                    result.versionNumber(), result.provider(), null, null,
                    null, null, null, null, null,
                    remapEvaluation(
                            event.payload().evaluation(),
                            result.persistedActivities(), result.persistedTransit())
            );
        }
        return new CompletionPayload(
                SUCCEEDED, event.runId(), result.versionId(), result.versionNumber(),
                result.provider(), provenance.requestedProviderMode(),
                provenance.primaryProvider(), provenance.actualProviders(),
                provenance.fallbackAttempted(), provenance.fallbackSucceeded(),
                provenance.fallbackReason(), remapFallbackOperations(
                        provenance.fallbackOperations(), result.persistedTransit()),
                remapEvaluation(
                        event.payload().evaluation(),
                        result.persistedActivities(), result.persistedTransit())
        );
    }

    private PlanningCompletedEvent.PlanEvaluation remapEvaluation(
            PlanningCompletedEvent.PlanEvaluation evaluation,
            List<ItineraryService.PersistedActivityReference> persistedActivities,
            List<ItineraryService.PersistedTransitReference> persistedTransit
    ) {
        if (evaluation == null) {
            return null;
        }
        List<PlanningCompletedEvent.EvaluationWarning> warnings = evaluation.warnings().stream()
                .map(warning -> new PlanningCompletedEvent.EvaluationWarning(
                        warning.code(), warning.severity(), warning.message(),
                        warning.dayIndex(), warning.entityType(),
                        remapEvaluationEntity(
                                warning.entityType(), warning.entityId(),
                                persistedActivities, persistedTransit),
                        warning.metricKey(), warning.actualValue(), warning.threshold()
                ))
                .toList();
        List<PlanningCompletedEvent.DecisionExplanation> decisions = evaluation.decisions().stream()
                .map(decision -> new PlanningCompletedEvent.DecisionExplanation(
                        decision.subjectType(),
                        remapEvaluationEntity(
                                decision.subjectType(), decision.subjectId(),
                                persistedActivities, persistedTransit),
                        decision.summary(), decision.reasonCodes(), decision.reasons(),
                        decision.constraintRefs(), decision.evidence(), decision.dayIndex()
                ))
                .toList();
        return new PlanningCompletedEvent.PlanEvaluation(
                evaluation.schemaVersion(), evaluation.evaluatorVersion(), evaluation.feasible(),
                evaluation.overallScore(), evaluation.dimensions(), warnings, decisions,
                evaluation.summary(), evaluation.evaluatedAt()
        );
    }

    private UUID remapEvaluationEntity(
            String entityType,
            UUID sourceId,
            List<ItineraryService.PersistedActivityReference> persistedActivities,
            List<ItineraryService.PersistedTransitReference> persistedTransit
    ) {
        if (sourceId == null) {
            return null;
        }
        List<UUID> matches;
        if ("TRANSIT".equals(entityType)) {
            matches = persistedTransit.stream()
                    .filter(reference -> Objects.equals(reference.sourceTransitId(), sourceId))
                    .map(ItineraryService.PersistedTransitReference::transitId)
                    .distinct()
                    .toList();
        } else if ("ACTIVITY".equals(entityType)) {
            matches = persistedActivities.stream()
                    .filter(reference -> Objects.equals(
                            reference.sourceActivityId(), sourceId))
                    .map(ItineraryService.PersistedActivityReference::activityId)
                    .distinct()
                    .toList();
        } else {
            return sourceId;
        }
        if (matches.isEmpty()) {
            throw rejected("Evaluation entity was not persisted with the itinerary");
        }
        if (matches.size() != 1) {
            throw rejected("Evaluation entity could not be mapped to one persisted identity");
        }
        return matches.getFirst();
    }

    private List<CompletionFallbackOperation> remapFallbackOperations(
            List<PlanningCompletedEvent.FallbackOperation> operations,
            List<ItineraryService.PersistedTransitReference> persistedTransit) {
        return operations.stream()
                .map(operation -> remapFallbackOperation(operation, persistedTransit))
                .toList();
    }

    private CompletionFallbackOperation remapFallbackOperation(
            PlanningCompletedEvent.FallbackOperation operation,
            List<ItineraryService.PersistedTransitReference> persistedTransit) {
        if (operation.operation() != PlanningCompletedEvent.ProviderOperation.ROUTE) {
            return CompletionFallbackOperation.from(operation);
        }
        List<ItineraryService.PersistedTransitReference> matches = persistedTransit.stream()
                .filter(reference -> Objects.equals(
                                reference.sourceTransitId(), operation.transitId())
                        && Objects.equals(reference.sourceFromActivityId(),
                                operation.fromActivityId())
                        && Objects.equals(reference.sourceToActivityId(),
                                operation.toActivityId()))
                .toList();
        if (matches.size() != 1) {
            throw rejected("Fallback operation could not be mapped to persisted transit identity");
        }
        ItineraryService.PersistedTransitReference match = matches.getFirst();
        return new CompletionFallbackOperation(
                operation.operation(), match.transitId(), match.fromActivityId(),
                match.toActivityId(), operation.requestedMode(),
                operation.actualProvider(), operation.errorCategory(),
                operation.errorCode(), operation.retryCount()
        );
    }

    private void persistFactImpacts(
            PlanningCompletedEvent event,
            UUID itineraryVersionId
    ) {
        for (PlanningCompletedEvent.FactImpact impact : event.payload().factImpacts()) {
            requireOne(factImpactMapper.insert(
                    new PlanningFactImpactMapper.PlanningFactImpactRecord(
                            UUID.randomUUID(),
                            itineraryVersionId,
                            event.taskId(),
                            impact.factId(),
                            impact.category(),
                            impact.date(),
                            impact.effect(),
                            impact.targetPoiId(),
                            impact.targetName(),
                            impact.reason(),
                            impact.sourceName(),
                            impact.sourceType(),
                            impact.sourceUrl(),
                            impact.reliabilityLevel(),
                            impact.checkedAt().toInstant(),
                            impact.evidence(),
                            impact.stale(),
                            impact.conflicted(),
                            impact.refreshFailed()
                    )
            ), "planning fact impact");
        }
    }

    private void updateTaskToSucceeded(
            PlanningCompletedEvent event,
            PlanningTaskCompletionRecord task,
            ItineraryService.CreateItineraryResult version,
            String eventType,
            String payloadJson) {
        Instant now = clock.instant();
        requireOne(taskMapper.updateTerminalStatus(
                task.id(), task.taskVersion(), SUCCEEDED, null, null
        ), "planning task status");
        recordFinalStageDuration(task.id(), now);
        metrics.taskFinished(task.taskType(), SUCCEEDED, java.time.Duration.between(task.createdAt(), now));
        publishAfterCommit(insertTaskEvent(new PlanningTaskEventRecord(
                null, event.eventId(), task.id(), eventType, 1, payloadJson, now
        )));
    }

    private void persistStaleFailure(PlanningCompletedEvent event,
                                     PlanningTaskCompletionRecord task,
                                     String errorCode,
                                     String message) {
        Instant now = clock.instant();
        requireOne(taskMapper.updateTerminalStatus(
                task.id(), task.taskVersion(), FAILED, errorCode, message
        ), "planning task status");
        recordFinalStageDuration(task.id(), now);
        metrics.taskFinished(task.taskType(), FAILED, java.time.Duration.between(task.createdAt(), now));
        publishAfterCommit(insertTaskEvent(new PlanningTaskEventRecord(
                null, event.eventId(), task.id(), "PLANNING_FAILED", 1,
                writeJson(new FailurePayload(
                        FAILED, errorCode, message
                )), now
        )));
    }

    private PlanningTaskEventRecord insertTaskEvent(PlanningTaskEventRecord event) {
        requireOne(taskEventMapper.insert(event), "planning task event");
        return taskEventMapper.findByEventId(event.eventId())
                .orElseThrow(() -> new IllegalStateException("Planning task event could not be read"));
    }

    private void publishAfterCommit(PlanningTaskEventRecord event) {
        eventPublisher.publishEvent(new PlanningTaskEventCreated(event));
    }

    private void recordFinalStageDuration(UUID taskId, Instant completedAt) {
        taskEventMapper.findLatestProgress(taskId).ifPresent(progress -> metrics.stageDuration(
                progress.stage(), java.time.Duration.between(progress.createdAt(), completedAt)
        ));
    }

    private void requireOne(int updatedRows, String operation) {
        if (updatedRows != 1) {
            throw new IllegalStateException("Could not persist " + operation);
        }
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not serialize planning task event", exception);
        }
    }

    private PlanningEventRejectedException rejected(String message) {
        return new PlanningEventRejectedException(message);
    }

    private record CompletionPayload(
            String status,
            UUID runId,
            UUID itineraryVersionId,
            int itineraryVersionNumber,
            String provider,
            PlanningCompletedEvent.ProviderExecutionMode requestedProviderMode,
            PlanningCompletedEvent.ProviderSource primaryProvider,
            List<PlanningCompletedEvent.ProviderSource> actualProviders,
            Boolean fallbackAttempted,
            Boolean fallbackSucceeded,
            String fallbackReason,
            List<CompletionFallbackOperation> fallbackOperations,
            PlanningCompletedEvent.PlanEvaluation evaluation
    ) {
    }

    private record CompletionFallbackOperation(
            PlanningCompletedEvent.ProviderOperation operation,
            UUID transitId,
            UUID fromActivityId,
            UUID toActivityId,
            PlanningCompletedEvent.ProviderExecutionMode requestedMode,
            PlanningCompletedEvent.ProviderSource actualProvider,
            PlanningCompletedEvent.ProviderErrorCategory errorCategory,
            String errorCode,
            int retryCount
    ) {
        private static CompletionFallbackOperation from(
                PlanningCompletedEvent.FallbackOperation operation) {
            return new CompletionFallbackOperation(
                    operation.operation(), operation.transitId(),
                    operation.fromActivityId(), operation.toActivityId(),
                    operation.requestedMode(), operation.actualProvider(),
                    operation.errorCategory(), operation.errorCode(),
                    operation.retryCount()
            );
        }
    }

    private record FailurePayload(String status, String errorCode, String message) {
    }
}
