package io.github.tobehardoo.trippilot.planning;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningProgressEvent;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PlanningProgressService implements PlanningProgressHandler {

    private final PlanningTaskMapper taskMapper;
    private final PlanningTaskEventMapper eventMapper;
    private final ObjectMapper objectMapper;
    private final Clock clock;
    private final ApplicationEventPublisher eventPublisher;
    private final PlanningMetrics metrics;

    public PlanningProgressService(PlanningTaskMapper taskMapper,
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
    @Override
    public void handle(PlanningProgressEvent event) {
        PlanningTaskCompletionRecord task = taskMapper.findCompletionContextForUpdate(event.taskId())
                .orElseThrow(() -> rejected("Planning task was not found"));
        if (!event.tripId().equals(task.tripId()) || !event.traceId().equals(task.traceId())) {
            throw rejected("Progress event does not match its planning task");
        }
        var existing = eventMapper.findByEventId(event.eventId());
        if (existing.isPresent()) {
            PlanningTaskEventRecord stored = existing.get();
            if (stored.taskId().equals(task.id()) && "PLANNING_PROGRESS".equals(stored.eventType())) {
                return;
            }
            throw rejected("Progress eventId already belongs to another planning task event");
        }
        if (!"QUEUED".equals(task.status()) && !"RUNNING".equals(task.status())) {
            throw rejected("Planning task cannot accept progress in status " + task.status());
        }
        var latestProgress = eventMapper.findLatestProgress(task.id());
        int latestSequence = eventMapper.findLatestProgressSequence(task.id());
        if (event.payload().sequence() <= latestSequence) {
            throw rejected("Planning progress sequence must increase monotonically");
        }
        if ("QUEUED".equals(task.status())) {
            requireOne(taskMapper.markRunning(task.id(), task.taskVersion()), "planning task status");
        }
        Instant now = clock.instant();
        PlanningTaskEventRecord stored = new PlanningTaskEventRecord(
                null,
                event.eventId(),
                task.id(),
                "PLANNING_PROGRESS",
                event.schemaVersion(),
                writeJson(event.payload()),
                now
        );
        requireOne(eventMapper.insert(stored), "planning progress event");
        PlanningTaskEventRecord persisted = eventMapper.findByEventId(event.eventId())
                .orElseThrow(() -> new IllegalStateException("Progress event could not be read"));
        eventPublisher.publishEvent(new PlanningTaskEventCreated(persisted));
        metrics.progressObserved(event.payload().stage());
        latestProgress.ifPresent(previous -> metrics.stageDuration(
                previous.stage(), Duration.between(previous.createdAt(), now)
        ));
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not serialize planning progress", exception);
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
