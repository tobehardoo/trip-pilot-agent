package io.github.tobehardoo.trippilot.planning;

import java.io.IOException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Component
public class PlanningTaskEventHub {

    private static final long STREAM_TIMEOUT_MILLIS = 30 * 60 * 1000L;
    private static final int TASK_MONITOR_COUNT = 256;

    private final Object[] taskMonitors = createTaskMonitors();
    private final Map<UUID, List<SseEmitter>> subscribers = new ConcurrentHashMap<>();
    private final PlanningTaskEventMapper eventMapper;
    private final ObjectMapper objectMapper;

    public PlanningTaskEventHub(PlanningTaskEventMapper eventMapper, ObjectMapper objectMapper) {
        this.eventMapper = eventMapper;
        this.objectMapper = objectMapper;
    }

    public SseEmitter subscribe(UUID taskId, long afterEventId, boolean taskIsTerminal) {
        SseEmitter emitter = new SseEmitter(STREAM_TIMEOUT_MILLIS);
        emitter.onCompletion(() -> remove(taskId, emitter));
        emitter.onTimeout(() -> remove(taskId, emitter));
        emitter.onError(exception -> remove(taskId, emitter));

        synchronized (monitorFor(taskId)) {
            List<PlanningTaskEventRecord> history = eventMapper.findAfter(taskId, afterEventId);
            boolean terminalEventReplayed = false;
            try {
                for (PlanningTaskEventRecord event : history) {
                    send(emitter, event);
                    terminalEventReplayed = terminalEventReplayed || isTerminal(event.eventType());
                }
            } catch (IOException | IllegalStateException exception) {
                emitter.completeWithError(exception);
                return emitter;
            }
            if (taskIsTerminal || terminalEventReplayed) {
                emitter.complete();
            } else {
                subscribers.computeIfAbsent(taskId, ignored -> new ArrayList<>()).add(emitter);
            }
        }
        return emitter;
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void publishAfterCommit(PlanningTaskEventCreated notification) {
        PlanningTaskEventRecord event = notification.event();
        boolean terminal = isTerminal(event.eventType());
        List<SseEmitter> taskSubscribers;
        synchronized (monitorFor(event.taskId())) {
            List<SseEmitter> registeredSubscribers = subscribers.get(event.taskId());
            if (registeredSubscribers == null) {
                return;
            }
            taskSubscribers = List.copyOf(registeredSubscribers);
            if (terminal) {
                subscribers.remove(event.taskId());
            }
        }
        for (SseEmitter emitter : taskSubscribers) {
            try {
                send(emitter, event);
                if (terminal) {
                    emitter.complete();
                }
            } catch (IOException | IllegalStateException exception) {
                if (!terminal) {
                    remove(event.taskId(), emitter);
                }
                emitter.completeWithError(exception);
            }
        }
    }

    private void send(SseEmitter emitter, PlanningTaskEventRecord event) throws IOException {
        emitter.send(SseEmitter.event()
                .id(Long.toString(event.id()))
                .name(event.eventType())
                .data(toView(event), MediaType.APPLICATION_JSON));
    }

    private TaskEventView toView(PlanningTaskEventRecord event) {
        try {
            return new TaskEventView(
                    event.id(), event.taskId(), event.eventType(), event.schemaVersion(),
                    objectMapper.readTree(event.payloadJson()), event.createdAt()
            );
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored planning task event payload is invalid", exception);
        }
    }

    private boolean isTerminal(String eventType) {
        return "PLANNING_COMPLETED".equals(eventType) || "PLANNING_FAILED".equals(eventType)
                || "PLANNING_CANCELLED".equals(eventType);
    }

    private void remove(UUID taskId, SseEmitter emitter) {
        synchronized (monitorFor(taskId)) {
            List<SseEmitter> taskSubscribers = subscribers.get(taskId);
            if (taskSubscribers == null) {
                return;
            }
            taskSubscribers.remove(emitter);
            if (taskSubscribers.isEmpty()) {
                subscribers.remove(taskId);
            }
        }
    }

    private Object monitorFor(UUID taskId) {
        int monitorIndex = (taskId.hashCode() & Integer.MAX_VALUE) % taskMonitors.length;
        return taskMonitors[monitorIndex];
    }

    private static Object[] createTaskMonitors() {
        Object[] monitors = new Object[TASK_MONITOR_COUNT];
        Arrays.setAll(monitors, ignored -> new Object());
        return monitors;
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
