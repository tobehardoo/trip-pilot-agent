package io.github.tobehardoo.trippilot.planning;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.EventRejectedException;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningProgressEvent;
import io.github.tobehardoo.trippilot.persistence.PersistenceSupport;
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
        // B14_FIX R5 (D05): RESULT_PUBLISHING is the worker's final progress
        // milestone, published on the progress route immediately before the
        // review event.  The two broker routes are consumed concurrently, so
        // the review listener may win the race and mark the task WAITING_USER
        // first; the legitimate publishing milestone must still be persisted.
        // Any other stage arriving after a terminal state remains ignored.
        boolean resultPublishingAfterWaitingUser = "WAITING_USER".equals(task.status())
                && "RESULT_PUBLISHING".equals(event.payload().stage());
        if (!resultPublishingAfterWaitingUser
                && ("SUCCEEDED".equals(task.status()) || "FAILED".equals(task.status())
                || "CANCELLED".equals(task.status()) || "WAITING_USER".equals(task.status()))) {
            // Progress and completion use distinct broker routes. A late
            // progress event is expected when any terminal outcome reaches
            // the server first, so it must not be retried.  WAITING_USER is
            // terminal for the worker too: the review already carries the
            // final outcome and late progress must be silently ignored
            // instead of being rejected into the dead-letter queue.
            return;
        }
        if (!resultPublishingAfterWaitingUser) {
            if (!"QUEUED".equals(task.status()) && !"RUNNING".equals(task.status())) {
                throw rejected("Planning task cannot accept progress in status " + task.status());
            }
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
        return PersistenceSupport.writeJson(objectMapper, value, "planning progress");
    }

    private void requireOne(int rows, String operation) {
        PersistenceSupport.requireOne(rows, operation);
    }

    private EventRejectedException rejected(String message) {
        return PlanningEventSupport.rejected(message);
    }
}
