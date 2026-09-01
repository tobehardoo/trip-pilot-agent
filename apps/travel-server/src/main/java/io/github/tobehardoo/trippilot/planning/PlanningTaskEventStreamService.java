package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.util.Set;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.infrastructure.sse.SseEventHub;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Service
public class PlanningTaskEventStreamService {

    private static final Set<String> TERMINAL_STATUSES =
            Set.of("SUCCEEDED", "FAILED", "CANCELLED", "WAITING_USER");

    private static final Set<String> TERMINAL_EVENT_TYPES = Set.of(
            "PLANNING_COMPLETED", "PLANNING_FAILED", "PLANNING_CANCELLED",
            "PLANNING_REVIEW_REQUIRED"
    );

    private final PlanningTaskMapper taskMapper;
    private final PlanningTaskEventMapper eventMapper;
    private final ObjectMapper objectMapper;
    private final SseEventHub eventHub;

    public PlanningTaskEventStreamService(PlanningTaskMapper taskMapper,
                                          PlanningTaskEventMapper eventMapper,
                                          ObjectMapper objectMapper,
                                          SseEventHub eventHub) {
        this.taskMapper = taskMapper;
        this.eventMapper = eventMapper;
        this.objectMapper = objectMapper;
        this.eventHub = eventHub;
    }

    @Transactional(readOnly = true)
    public SseEmitter subscribe(UUID ownerId, UUID taskId, Long lastEventId) {
        PlanningTaskRecord task = taskMapper.findOwnedById(taskId, ownerId)
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND, "PLANNING_TASK_NOT_FOUND", "Planning task was not found"
                ));
        long afterEventId = lastEventId == null ? 0 : Math.max(0, lastEventId);
        boolean taskIsTerminal = TERMINAL_STATUSES.contains(task.status());
        return eventHub.subscribe(taskId, emitter -> {
            boolean terminalReplayed = false;
            for (PlanningTaskEventRecord event :
                    eventMapper.findAfter(taskId, afterEventId)) {
                eventHub.send(emitter, toEvent(event));
                terminalReplayed = terminalReplayed
                        || TERMINAL_EVENT_TYPES.contains(event.eventType());
            }
            return terminalReplayed;
        }, taskIsTerminal);
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void publishAfterCommit(PlanningTaskEventCreated notification) {
        PlanningTaskEventRecord event = notification.event();
        eventHub.publish(event.taskId(), toEvent(event),
                TERMINAL_EVENT_TYPES.contains(event.eventType()));
    }

    private SseEventHub.SseEvent toEvent(PlanningTaskEventRecord event) {
        return new SseEventHub.SseEvent(event.id(), event.eventType(), toView(event));
    }

    private JsonNode toView(PlanningTaskEventRecord event) {
        try {
            return objectMapper.valueToTree(new TaskEventView(
                    event.id(), event.taskId(), event.eventType(), event.schemaVersion(),
                    objectMapper.readTree(event.payloadJson()), event.createdAt()
            ));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored planning task event payload is invalid", exception);
        }
    }

    public record TaskEventView(
            long eventId,
            UUID taskId,
            String eventType,
            int schemaVersion,
            JsonNode payload,
            Instant createdAt
    ) {
    }
}
