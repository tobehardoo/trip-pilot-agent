package io.github.tobehardoo.trippilot.agentdialog;

import java.time.Instant;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.infrastructure.sse.SseEventHub;
import io.github.tobehardoo.trippilot.trip.TripService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Service
public class AgentDialogEventStreamService {

    private final TripService tripService;
    private final AgentDialogMessageMapper messageMapper;
    private final ObjectMapper objectMapper;
    private final SseEventHub eventHub;

    AgentDialogEventStreamService(TripService tripService,
                                  AgentDialogMessageMapper messageMapper,
                                  ObjectMapper objectMapper,
                                  SseEventHub eventHub) {
        this.tripService = tripService;
        this.messageMapper = messageMapper;
        this.objectMapper = objectMapper;
        this.eventHub = eventHub;
    }

    @Transactional(readOnly = true)
    public SseEmitter subscribe(UUID ownerId, UUID tripId, Long lastMessageId) {
        // Ownership gate: a trip the caller cannot read has no dialog stream.
        tripService.get(ownerId, tripId);
        long afterMessageId = lastMessageId == null ? 0 : Math.max(0, lastMessageId);
        // A dialog has many runs (one per turn), so the stream never completes
        // — the conversation may simply continue.
        return eventHub.subscribe(tripId, emitter -> {
            for (AgentDialogMessageRecord message :
                    messageMapper.findAfter(tripId, afterMessageId)) {
                eventHub.send(emitter, toEvent(message));
            }
            return false;
        }, false);
    }

    /**
     * AFTER_COMMIT keeps the replay-vs-live ordering consistent with the
     * planning stream: subscribers only ever see persisted messages.
     */
    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void publishAfterCommit(AgentDialogEventCreated notification) {
        AgentDialogMessageRecord message = notification.message();
        eventHub.publish(message.tripId(), toEvent(message), false);
    }

    private SseEventHub.SseEvent toEvent(AgentDialogMessageRecord message) {
        return new SseEventHub.SseEvent(message.id(), message.eventType(), toView(message));
    }

    private JsonNode toView(AgentDialogMessageRecord message) {
        try {
            return objectMapper.valueToTree(new DialogEventView(
                    message.id(), message.tripId(), message.runId(), message.eventType(),
                    message.schemaVersion(),
                    objectMapper.readTree(message.payloadJson()), message.createdAt()
            ));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored agent dialog payload is invalid", exception);
        }
    }

    public record DialogEventView(
            long eventId,
            UUID tripId,
            UUID runId,
            String eventType,
            int schemaVersion,
            JsonNode payload,
            Instant createdAt
    ) {
    }
}
