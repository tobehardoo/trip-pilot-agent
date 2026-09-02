package io.github.tobehardoo.trippilot.agentdialog;

import java.time.Clock;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.infrastructure.mq.OutboxEventRecord;
import io.github.tobehardoo.trippilot.infrastructure.mq.OutboxMapper;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * P2.8a: queues agent dialog commands (AGENT_START / AGENT_RESUME) through
 * the transactional outbox — the trigger side of the user-visible loop.
 * The old HTTP dialog channel stays untouched (ADR-016 §2).
 */
@Service
public class AgentDialogCommandService {

    private static final String START_COMMAND_TYPE = "AGENT_START";
    private static final String START_ROUTING_KEY = "agent.start";
    private static final String RESUME_COMMAND_TYPE = "AGENT_RESUME";
    private static final String RESUME_ROUTING_KEY = "agent.resume";
    private static final int MAX_TEXT_LENGTH = 2000;

    private final OutboxMapper outboxMapper;
    private final TripOwnershipGuard ownershipGuard;
    private final ObjectMapper objectMapper;
    private final Clock clock;

    AgentDialogCommandService(
            OutboxMapper outboxMapper,
            TripOwnershipGuard ownershipGuard,
            ObjectMapper objectMapper,
            Clock clock
    ) {
        this.outboxMapper = outboxMapper;
        this.ownershipGuard = ownershipGuard;
        this.objectMapper = objectMapper;
        this.clock = clock;
    }

    public record CommandQueued(UUID eventId, String status) {
    }

    /**
     * Start a dialog run.  {@code tripContext} (destination/dates from the trip
     * entity) is included in the payload so the agent worker can seed the dialog
     * with read-only TRIP facts instead of re-asking what the user already set.
     */
    @Transactional
    public CommandQueued startRun(
            UUID ownerId, UUID tripId, UUID eventId, String message,
            HttpAgentDialogClient.TripContext tripContext
    ) {
        requireTripOwnership(ownerId, tripId);
        requireText(message, "message");
        Map<String, Object> envelope = envelope(
                START_COMMAND_TYPE, eventId, tripId, null, ownerId, message
        );
        addTripContextToPayload(envelope, tripContext);
        writeCommand(envelope, START_COMMAND_TYPE, START_ROUTING_KEY, tripId, eventId);
        return new CommandQueued(eventId, "QUEUED");
    }

    @Transactional
    public CommandQueued resumeRun(
            UUID ownerId, UUID tripId, UUID runId, UUID eventId, String answer
    ) {
        requireTripOwnership(ownerId, tripId);
        requireText(answer, "answer");
        Map<String, Object> envelope = envelope(
                RESUME_COMMAND_TYPE, eventId, tripId, runId, null, answer
        );
        writeCommand(envelope, RESUME_COMMAND_TYPE, RESUME_ROUTING_KEY, tripId, eventId);
        return new CommandQueued(eventId, "QUEUED");
    }

    private Map<String, Object> envelope(
            String eventType,
            UUID eventId,
            UUID tripId,
            UUID runId,
            UUID userId,
            String text
    ) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put(runId == null ? "message" : "answer", text);
        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("eventType", eventType);
        envelope.put("schemaVersion", 1);
        envelope.put("eventId", eventId.toString());
        envelope.put("traceId", UUID.randomUUID().toString());
        envelope.put("tripId", tripId.toString());
        if (runId != null) {
            envelope.put("runId", runId.toString());
        }
        if (userId != null) {
            envelope.put("userId", userId.toString());
        }
        envelope.put("occurredAt", OffsetDateTime.now(clock).toString());
        envelope.put("payload", payload);
        return envelope;
    }

    private void writeCommand(
            Map<String, Object> envelope,
            String commandType,
            String routingKey,
            UUID tripId,
            UUID eventId
    ) {
        String payloadJson;
        try {
            payloadJson = objectMapper.writeValueAsString(envelope);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not serialize agent dialog command", exception);
        }
        OutboxEventRecord record = new OutboxEventRecord(
                eventId,
                "agent_dialog",
                tripId,
                commandType,
                routingKey,
                payloadJson,
                "PENDING",
                0,
                clock.instant(),
                null,
                clock.instant(),
                null
        );
        try {
            if (outboxMapper.insert(record) != 1) {
                throw new IllegalStateException("Could not queue agent dialog command");
            }
        } catch (DuplicateKeyException exception) {
            // Same Idempotency-Key replayed — the command is already queued.
        }
    }

    private void requireTripOwnership(UUID ownerId, UUID tripId) {
        ownershipGuard.requireOwnership(ownerId, tripId);
    }

    private void requireText(String value, String field) {
        if (value == null || value.isBlank() || value.length() > MAX_TEXT_LENGTH) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "INVALID_" + field.toUpperCase(),
                    field + " must be 1.." + MAX_TEXT_LENGTH + " non-blank characters"
            );
        }
    }

    private void addTripContextToPayload(
            Map<String, Object> envelope,
            HttpAgentDialogClient.TripContext tripContext
    ) {
        Map<String, String> contextPayload = new LinkedHashMap<>();
        contextPayload.put("destination", tripContext.destination());
        contextPayload.put("start_date", tripContext.startDate());
        contextPayload.put("end_date", tripContext.endDate());
        ((Map<String, Object>) envelope.get("payload")).put("tripContext", contextPayload);
    }
}
