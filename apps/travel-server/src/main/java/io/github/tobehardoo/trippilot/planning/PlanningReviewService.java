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
        guard.validateDates(event.payload().itinerary().days(), task);
        if (guard.isStaleTripBaseline(task)) {
            persistStaleFailure(event, task, STALE_TRIP_VERSION,
                    "Trip constraints changed while planning was running");
            return;
        }
        if ("REPLAN".equals(task.taskType())
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
                        event.payload().itinerary(),
                        event.payload().knowledge(),
                        event.payload().factImpacts(),
                        event.payload().providerProvenance(),
                        event.payload().feasibilityReport()
                )), now
        );
        requireOne(taskEventMapper.insert(record), "planning task event");
        eventPublisher.publishEvent(new PlanningTaskEventCreated(record));
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
        eventPublisher.publishEvent(new PlanningTaskEventCreated(record));
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

    private record ReviewPayload(
            String status,
            UUID runId,
            String provider,
            PlanningCompletedEvent.Itinerary candidateItinerary,
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
