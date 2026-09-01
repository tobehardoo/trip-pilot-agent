package io.github.tobehardoo.trippilot.infrastructure.mq;

import io.github.tobehardoo.trippilot.common.EventContractException;
import java.io.IOException;
import java.util.Set;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import org.springframework.stereotype.Component;

@Component
public class AgentRunFinishedEventParser {

    private static final int MAX_REASON_LENGTH = 60;
    private static final int MAX_MESSAGE_LENGTH = 300;
    private static final Set<String> STATUSES = Set.of("STOPPED", "FAILED", "EXPIRED", "ANSWERED");

    private final ObjectMapper objectMapper;
    private final ObjectReader reader;

    public AgentRunFinishedEventParser(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.reader = objectMapper.readerFor(AgentRunFinishedEvent.class)
                .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }

    public AgentRunFinishedEvent parse(byte[] body) {
        try {
            JsonNode tree = objectMapper.readTree(body);
            if (tree == null) {
                throw invalid("event body must contain a JSON object");
            }
            validateJsonTypes(tree);
            AgentRunFinishedEvent event = reader.readValue(tree.traverse(objectMapper));
            validate(event);
            return event;
        } catch (IOException exception) {
            throw new EventContractException("Invalid AGENT_RUN_FINISHED event", exception);
        }
    }

    private void validateJsonTypes(JsonNode event) {
        if (!event.isObject() || !event.path("eventType").isTextual()
                || !event.path("schemaVersion").isIntegralNumber()
                || !event.path("occurredAt").isTextual()) {
            throw invalid("event envelope field types do not match the JSON Schema");
        }
        for (String idField : new String[]{"eventId", "traceId", "tripId", "runId"}) {
            if (!event.path(idField).isTextual()) {
                throw invalid("event envelope field types do not match the JSON Schema");
            }
        }
        JsonNode payload = event.path("payload");
        if (!payload.isObject() || !payload.path("status").isTextual()
                || !payload.path("reasonCode").isTextual()
                || !payload.path("message").isTextual()) {
            throw invalid("payload field types do not match the JSON Schema");
        }
    }

    private void validate(AgentRunFinishedEvent event) {
        if (!"AGENT_RUN_FINISHED".equals(event.eventType()) || event.schemaVersion() != 1) {
            throw invalid("unsupported eventType or schemaVersion");
        }
        if (event.eventId() == null || event.traceId() == null || event.tripId() == null
                || event.runId() == null || event.occurredAt() == null
                || event.payload() == null) {
            throw invalid("event envelope fields are required");
        }
        AgentRunFinishedEvent.Payload payload = event.payload();
        if (!STATUSES.contains(payload.status())
                || !validText(payload.reasonCode(), MAX_REASON_LENGTH)
                || !validText(payload.message(), MAX_MESSAGE_LENGTH)) {
            throw invalid("agent run finished payload is invalid");
        }
    }

    private boolean validText(String value, int maxLength) {
        return value != null && !value.isBlank() && value.length() <= maxLength;
    }

    private EventContractException invalid(String detail) {
        return new EventContractException("Invalid AGENT_RUN_FINISHED event: " + detail);
    }
}
