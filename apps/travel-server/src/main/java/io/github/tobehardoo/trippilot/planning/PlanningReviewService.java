package io.github.tobehardoo.trippilot.planning;

import java.time.Clock;
import java.time.Instant;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningReviewRequiredEvent;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Transitions a planning task into WAITING_USER on PLANNING_REVIEW_REQUIRED.
 *
 * A review never creates an itinerary version and never touches the trip's
 * current version.  Re-deliveries of the same event id for the same task and
 * event type are idempotent; event ids owned by another task/type, identity
 * mismatches, candidate dates outside the trip range and stale trip/replan
 * baselines are all rejected.  A stale baseline becomes a FAILED task with a
 * PLANNING_FAILED task event (STALE_TRIP_VERSION / STALE_ITINERARY_VERSION),
 * reusing the existing failure envelope rather than inventing a new one.
 */
@Service
public class PlanningReviewService implements PlanningReviewHandler {

    private static final String WAITING_USER = "WAITING_USER";
    private static final String FAILED = "FAILED";
    private static final String STALE_TRIP_VERSION = "STALE_TRIP_VERSION";
    private static final String STALE_ITINERARY_VERSION = "STALE_ITINERARY_VERSION";

    private final PlanningTaskMapper taskMapper;
    private final PlanningTaskEventMapper taskEventMapper;
    private final PlanningOutcomeGuard guard;
    private final ObjectMapper objectMapper;
    private final Clock clock;
    private final ApplicationEventPublisher eventPublisher;
    private ItineraryCurrentVersionProvider currentVersionProvider;

    public PlanningReviewService(PlanningTaskMapper taskMapper,
                                 PlanningTaskEventMapper taskEventMapper,
                                 PlanningOutcomeGuard guard,
                                 ObjectMapper objectMapper,
                                 Clock clock,
                                 ApplicationEventPublisher eventPublisher,
                                 ItineraryCurrentVersionProvider currentVersionProvider) {
        this.taskMapper = taskMapper;
        this.taskEventMapper = taskEventMapper;
        this.guard = guard;
        this.objectMapper = objectMapper;
        this.clock = clock;
        this.eventPublisher = eventPublisher;
        this.currentVersionProvider = currentVersionProvider;
    }

    /**
     * Test seam: pins the current itinerary version used by the replan
     * baseline check without needing the full ItineraryService graph.
     */
    void setReplanCurrentVersionId(UUID currentVersionId) {
        this.currentVersionProvider = tripId -> currentVersionId;
    }

    @Transactional
    @Override
    public void handle(PlanningReviewRequiredEvent event) {
        PlanningTaskCompletionRecord task = taskMapper.findCompletionContextForUpdate(event.taskId())
                .orElseThrow(() -> rejected("Planning task was not found"));
        guard.validateIdentity(event.tripId(), event.traceId(), task, "Review event");
        var existingEvent = taskEventMapper.findByEventId(event.eventId());
        if (existingEvent.isPresent()) {
            PlanningTaskEventRecord existing = existingEvent.get();
            boolean isSameReviewDelivery = existing.taskId().equals(task.id())
                    && "PLANNING_REVIEW_REQUIRED".equals(existing.eventType());
            if (isSameReviewDelivery) {
                return;
            }
            throw rejected("Review eventId already belongs to another planning task event");
        }
        if (!"QUEUED".equals(task.status()) && !"RUNNING".equals(task.status())) {
            throw rejected("Planning task cannot accept a review event in status " + task.status());
        }
        validateReport(event);
        validateCandidateIntegrity(event);
        guard.validateDates(event.payload().itinerary().days(), task);
        if (guard.isStaleTripBaseline(task)) {
            persistStaleFailure(event, task, STALE_TRIP_VERSION,
                    "Trip constraints changed while planning was running");
            return;
        }
        if (("REPLAN".equals(task.taskType())
                || "EDIT_VALIDATE".equals(task.taskType())
                || "ROLLBACK_VALIDATE".equals(task.taskType()))
                && guard.isStaleReplanBaseline(task, currentVersionProvider.currentVersionId(
                        task.tripId()))) {
            persistStaleFailure(event, task, STALE_ITINERARY_VERSION,
                    "The itinerary changed while local replanning was running");
            return;
        }
        requireOne(taskMapper.markWaitingUser(task.id(), task.taskVersion()),
                "planning task status");
        Instant now = clock.instant();
        PlanningTaskEventRecord record = new PlanningTaskEventRecord(
                null, event.eventId(), task.id(), "PLANNING_REVIEW_REQUIRED", 1,
                writeJson(new ReviewPayload(
                        WAITING_USER,
                        event.runId(),
                        event.payload().provider(),
                        event.payload().validatedItineraryJson(),
                        event.payload().knowledge(),
                        event.payload().factImpacts(),
                        event.payload().providerProvenance(),
                        event.payload().feasibilityReport()
                )), now
        );
        requireOne(taskEventMapper.insert(record), "planning task event");
        eventPublisher.publishEvent(new PlanningTaskEventCreated(stored(record)));
    }

    private void persistStaleFailure(PlanningReviewRequiredEvent event,
                                     PlanningTaskCompletionRecord task,
                                     String errorCode,
                                     String message) {
        Instant now = clock.instant();
        requireOne(taskMapper.updateTerminalStatus(
                task.id(), task.taskVersion(), FAILED, errorCode, message
        ), "planning task status");
        PlanningTaskEventRecord record = new PlanningTaskEventRecord(
                null, event.eventId(), task.id(), "PLANNING_FAILED", 1,
                writeJson(new FailurePayload(FAILED, errorCode, message)), now
        );
        requireOne(taskEventMapper.insert(record), "planning task event");
        eventPublisher.publishEvent(new PlanningTaskEventCreated(stored(record)));
    }

    private PlanningTaskEventRecord stored(PlanningTaskEventRecord record) {
        return taskEventMapper.findByEventId(record.eventId())
                .orElseThrow(() -> new IllegalStateException(
                        "Planning task event could not be read"));
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

    private void validateReport(PlanningReviewRequiredEvent event) {
        io.github.tobehardoo.trippilot.feasibility.FeasibilityReport report =
                event.payload().feasibilityReport();
        if (report == null) {
            throw rejected("Review event is missing its feasibility report");
        }
        try {
            io.github.tobehardoo.trippilot.feasibility.FeasibilityReportValidator.validate(report);
        } catch (IllegalArgumentException exception) {
            throw rejected("Review event feasibility report is invalid: "
                    + exception.getMessage());
        }
        if (report.status() == io.github.tobehardoo.trippilot.feasibility.FeasibilityStatus.VERIFIED) {
            throw rejected("Review event feasibility report must be UNVERIFIED or NEEDS_REPAIR");
        }
    }

    /**
     * Second-line integrity gate for the review candidate (the service may be
     * invoked without the parser, so it must not blindly trust the event).
     *
     * Requires:
     * <ol>
     *   <li>the validated raw itinerary snapshot exists and is an object;</li>
     *   <li>the raw snapshot matches the report fingerprint;</li>
     *   <li>the raw snapshot strictly deserialises into the typed
     *       {@link PlanningCompletedEvent.Itinerary} and is semantically
     *       equal to {@code event.payload().itinerary()} (no unknown fields,
     *       no structure drift).</li>
     * </ol>
     *
     * All failures happen before markWaitingUser / task_event insert / SSE
     * publish.
     */
    private void validateCandidateIntegrity(PlanningReviewRequiredEvent event) {
        com.fasterxml.jackson.databind.JsonNode raw =
                event.payload().validatedItineraryJson();
        if (raw == null || !raw.isObject()) {
            throw rejected("Review event is missing its validated itinerary snapshot");
        }
        io.github.tobehardoo.trippilot.feasibility.FeasibilityReport report =
                event.payload().feasibilityReport();
        if (report == null
                || !io.github.tobehardoo.trippilot.feasibility.ItineraryFingerprintVerifier
                        .matches(raw, report.itineraryFingerprint())) {
            throw rejected("Review event raw candidate does not match the report fingerprint");
        }
        PlanningCompletedEvent.Itinerary typed;
        try {
            typed = objectMapper.readerFor(PlanningCompletedEvent.Itinerary.class)
                    .with(com.fasterxml.jackson.databind.DeserializationFeature
                            .FAIL_ON_UNKNOWN_PROPERTIES)
                    .readValue(raw);
        } catch (java.io.IOException exception) {
            throw rejected("Review event raw candidate is not a valid itinerary: "
                    + exception.getMessage());
        }
        if (!typed.equals(event.payload().itinerary())) {
            throw rejected("Review event raw candidate differs from the typed itinerary");
        }
    }

    private PlanningEventRejectedException rejected(String message) {
        return new PlanningEventRejectedException(message);
    }

    private record ReviewPayload(
            String status,
            UUID runId,
            String provider,
            com.fasterxml.jackson.databind.JsonNode candidateItinerary,
            PlanningCompletedEvent.KnowledgeEvidence knowledge,
            java.util.List<PlanningCompletedEvent.FactImpact> factImpacts,
            PlanningCompletedEvent.ProviderProvenance providerProvenance,
            io.github.tobehardoo.trippilot.feasibility.FeasibilityReport feasibilityReport
    ) {
    }
    private record FailurePayload(
            String status,
            String errorCode,
            String message
    ) {
    }
}
