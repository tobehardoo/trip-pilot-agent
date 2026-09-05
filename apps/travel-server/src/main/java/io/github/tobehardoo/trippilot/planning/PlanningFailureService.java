package io.github.tobehardoo.trippilot.planning;

import java.time.Clock;
import java.time.Instant;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.EventRejectedException;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningFailedEvent;
import io.github.tobehardoo.trippilot.persistence.PersistenceSupport;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PlanningFailureService {

    private static final Logger log = LoggerFactory.getLogger(PlanningFailureService.class);

    private final PlanningTaskMapper taskMapper;
    private final PlanningTaskEventMapper eventMapper;
    private final io.github.tobehardoo.trippilot.trip.TripMapper tripMapper;
    private final io.github.tobehardoo.trippilot.itinerary.ItineraryMapper itineraryMapper;
    private final ObjectMapper objectMapper;
    private final Clock clock;
    private final ApplicationEventPublisher eventPublisher;
    private final PlanningMetrics metrics;

    public PlanningFailureService(PlanningTaskMapper taskMapper,
                                  PlanningTaskEventMapper eventMapper,
                                  io.github.tobehardoo.trippilot.trip.TripMapper tripMapper,
                                  io.github.tobehardoo.trippilot.itinerary.ItineraryMapper itineraryMapper,
                                  ObjectMapper objectMapper,
                                  Clock clock,
                                  ApplicationEventPublisher eventPublisher,
                                  PlanningMetrics metrics) {
        this.taskMapper = taskMapper;
        this.eventMapper = eventMapper;
        this.tripMapper = tripMapper;
        this.itineraryMapper = itineraryMapper;
        this.objectMapper = objectMapper;
        this.clock = clock;
        this.eventPublisher = eventPublisher;
        this.metrics = metrics;
    }

    @Transactional
    public void handle(PlanningFailedEvent event) {
        try (PlanningLogContext ctx = PlanningLogContext.open()
                .put(PlanningLogContext.EVENT_TYPE, "PLANNING_FAILED")
                .put(PlanningLogContext.OUTCOME_STATUS, "FAILED")) {
            handleInScope(event);
        }
    }

    private void handleInScope(PlanningFailedEvent event) {
        PlanningTaskCompletionRecord task = taskMapper.findCompletionContextForUpdate(event.taskId())
                .orElseThrow(() -> rejected("Planning task was not found"));
        if (!event.tripId().equals(task.tripId()) || !event.traceId().equals(task.traceId())) {
            throw rejected("Failed event does not match its planning task");
        }
        var existing = eventMapper.findByEventId(event.eventId());
        if (existing.isPresent()) {
            PlanningTaskEventRecord stored = existing.get();
            if (stored.taskId().equals(task.id()) && "PLANNING_FAILED".equals(stored.eventType())) {
                log.info("duplicate ignored: failure event already applied");
                return;
            }
            throw rejected("Failed eventId already belongs to another planning task event");
        }
        if ("FAILED".equals(task.status())) {
            log.info("duplicate ignored: task already FAILED");
            return;
        }
        if (!"QUEUED".equals(task.status()) && !"RUNNING".equals(task.status())) {
            throw rejected("Planning task cannot accept a failure event in status " + task.status());
        }
        PlanningFailedEvent.Payload payload = event.payload();
        Instant now = clock.instant();
        requireOne(taskMapper.updateTerminalStatus(
                task.id(), task.taskVersion(), "FAILED",
                payload.errorCode(), payload.displayMessage()
        ), "planning task status");
        // Trip phase rollback: a trip that already has an itinerary (replan /
        // candidate validation) stays COMPLETED; a first attempt falls back
        // to FAILED so the workspace can leave the planning view and surface
        // the failure instead of rendering an endless "planning" state.
        boolean hasItinerary = itineraryMapper.findStateForUpdate(task.tripId())
                .map(state -> state.currentVersionId() != null)
                .orElse(false);
        tripMapper.updateStatus(task.tripId(), hasItinerary ? "COMPLETED" : "FAILED");
        eventMapper.findLatestProgress(task.id()).ifPresent(progress -> metrics.stageDuration(
                progress.stage(), java.time.Duration.between(progress.createdAt(), now)
        ));
        metrics.taskFinished(task.taskType(), "FAILED", java.time.Duration.between(task.createdAt(), now));
        PlanningTaskEventRecord record = new PlanningTaskEventRecord(
                null, event.eventId(), task.id(), "PLANNING_FAILED", event.schemaVersion(),
                writeJson(payload), now
        );
        requireOne(eventMapper.insert(record), "planning task failure event");
        PlanningTaskEventRecord stored = eventMapper.findByEventId(event.eventId())
                .orElseThrow(() -> new IllegalStateException("Failure event could not be read"));
        eventPublisher.publishEvent(new PlanningTaskEventCreated(stored));
        log.warn("task failed: errorCode={} errorCategory={}",
                payload.errorCode(), payload.errorCategory());
    }

    private String writeJson(Object value) {
        return PersistenceSupport.writeJson(objectMapper, value, "planning failure");
    }

    private void requireOne(int rows, String operation) {
        PersistenceSupport.requireOne(rows, operation);
    }

    private EventRejectedException rejected(String message) {
        return PlanningEventSupport.rejected(message);
    }
}
