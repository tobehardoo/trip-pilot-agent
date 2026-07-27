package io.github.tobehardoo.trippilot.planning;

import java.time.Clock;
import java.time.Instant;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningFailedEvent;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PlanningFailureService {

    private final PlanningTaskMapper taskMapper;
    private final PlanningTaskEventMapper eventMapper;
    private final ObjectMapper objectMapper;
    private final Clock clock;
    private final ApplicationEventPublisher eventPublisher;
    private final PlanningMetrics metrics;

    public PlanningFailureService(PlanningTaskMapper taskMapper,
                                  PlanningTaskEventMapper eventMapper,
                                  ObjectMapper objectMapper,
                                  Clock clock,
                                  ApplicationEventPublisher eventPublisher,
                                  PlanningMetrics metrics) {
        this.taskMapper = taskMapper;
        this.eventMapper = eventMapper;
        this.objectMapper = objectMapper;
        this.clock = clock;
        this.eventPublisher = eventPublisher;
        this.metrics = metrics;
    }

    @Transactional
    public void handle(PlanningFailedEvent event) {
        PlanningTaskCompletionRecord task = taskMapper.findCompletionContextForUpdate(event.taskId())
                .orElseThrow(() -> rejected("Planning task was not found"));
        if (!event.tripId().equals(task.tripId()) || !event.traceId().equals(task.traceId())) {
            throw rejected("Failed event does not match its planning task");
        }
        var existing = eventMapper.findByEventId(event.eventId());
        if (existing.isPresent()) {
            PlanningTaskEventRecord stored = existing.get();
            if (stored.taskId().equals(task.id()) && "PLANNING_FAILED".equals(stored.eventType())) {
                return;
            }
            throw rejected("Failed eventId already belongs to another planning task event");
        }
        if (!"QUEUED".equals(task.status()) && !"RUNNING".equals(task.status())) {
            throw rejected("Planning task cannot accept a failure event in status " + task.status());
        }
        PlanningFailedEvent.Payload payload = event.payload();
        Instant now = clock.instant();
        requireOne(taskMapper.updateTerminalStatus(
                task.id(), task.taskVersion(), "FAILED", payload.errorCode(), payload.message()
        ), "planning task status");
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
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not serialize planning failure", exception);
        }
    }

    private void requireOne(int rows, String operation) {
        if (rows != 1) {
            throw new IllegalStateException("Could not persist " + operation);
        }
    }

    private PlanningEventRejectedException rejected(String message) {
        return new PlanningEventRejectedException(message);
    }
}
