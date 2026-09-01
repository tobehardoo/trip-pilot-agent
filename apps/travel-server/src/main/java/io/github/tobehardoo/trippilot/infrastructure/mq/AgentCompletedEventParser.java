package io.github.tobehardoo.trippilot.infrastructure.mq;

import io.github.tobehardoo.trippilot.common.EventContractException;
import java.io.IOException;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import org.springframework.stereotype.Component;

@Component
public class AgentCompletedEventParser {

    private static final int MAX_SUMMARY_LENGTH = 300;

    private final ObjectMapper objectMapper;
    private final ObjectReader reader;

    public AgentCompletedEventParser(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.reader = objectMapper.readerFor(AgentCompletedEvent.class)
                .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }

    public AgentCompletedEvent parse(byte[] body) {
        try {
            JsonNode tree = objectMapper.readTree(body);
            if (tree == null) {
                throw invalid("event body must contain a JSON object");
            }
            validateJsonTypes(tree);
            AgentCompletedEvent event = reader.readValue(tree.traverse(objectMapper));
            validate(event);
            return event;
        } catch (IOException exception) {
            throw new EventContractException("Invalid AGENT_COMPLETED event", exception);
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
        if (!payload.isObject() || !payload.path("summary").isTextual()
                || !payload.path("itinerary").isObject()) {
            throw invalid("payload field types do not match the JSON Schema");
        }
        JsonNode slots = payload.path("slots");
        if (!slots.isMissingNode() && !slots.isNull() && !slots.isObject()) {
            throw invalid("payload field types do not match the JSON Schema");
        }
    }

    private void validate(AgentCompletedEvent event) {
        if (!"AGENT_COMPLETED".equals(event.eventType()) || event.schemaVersion() != 1) {
            throw invalid("unsupported eventType or schemaVersion");
        }
        if (event.eventId() == null || event.traceId() == null || event.tripId() == null
                || event.runId() == null || event.occurredAt() == null
                || event.payload() == null) {
            throw invalid("event envelope fields are required");
        }
        if (!validText(event.payload().summary(), MAX_SUMMARY_LENGTH)) {
            throw invalid("agent completed summary is invalid");
        }
    }

    private boolean validText(String value, int maxLength) {
        return value != null && !value.isBlank() && value.length() <= maxLength;
    }

    private EventContractException invalid(String detail) {
        return new EventContractException("Invalid AGENT_COMPLETED event: " + detail);
    }
}
