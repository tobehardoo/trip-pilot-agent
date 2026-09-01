package io.github.tobehardoo.trippilot.infrastructure.mq;

import io.github.tobehardoo.trippilot.common.EventContractException;
import java.io.IOException;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import org.springframework.stereotype.Component;

@Component
public class AgentStepEventParser {

    private static final int MAX_TOOL_LENGTH = 60;
    private static final int MAX_SUMMARY_LENGTH = 300;
    private static final int MAX_ERROR_CODE_LENGTH = 60;

    private final ObjectMapper objectMapper;
    private final ObjectReader reader;

    public AgentStepEventParser(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.reader = objectMapper.readerFor(AgentStepEvent.class)
                .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }

    public AgentStepEvent parse(byte[] body) {
        try {
            JsonNode tree = objectMapper.readTree(body);
            if (tree == null) {
                throw invalid("event body must contain a JSON object");
            }
            validateJsonTypes(tree);
            AgentStepEvent event = reader.readValue(tree.traverse(objectMapper));
            validate(event);
            return event;
        } catch (IOException exception) {
            throw new EventContractException("Invalid AGENT_STEP event", exception);
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
        if (!payload.isObject() || !payload.path("seq").isIntegralNumber()
                || !payload.path("tool").isTextual()
                || !payload.path("ok").isBoolean()
                || !payload.path("summary").isTextual()) {
            throw invalid("payload field types do not match the JSON Schema");
        }
        JsonNode errorCode = payload.path("errorCode");
        if (!errorCode.isMissingNode() && !errorCode.isNull() && !errorCode.isTextual()) {
            throw invalid("payload field types do not match the JSON Schema");
        }
    }

    private void validate(AgentStepEvent event) {
        if (!"AGENT_STEP".equals(event.eventType()) || event.schemaVersion() != 1) {
            throw invalid("unsupported eventType or schemaVersion");
        }
        if (event.eventId() == null || event.traceId() == null || event.tripId() == null
                || event.runId() == null || event.occurredAt() == null
                || event.payload() == null) {
            throw invalid("event envelope fields are required");
        }
        AgentStepEvent.Payload payload = event.payload();
        if (payload.seq() < 0 || !validText(payload.tool(), MAX_TOOL_LENGTH)
                || !validText(payload.summary(), MAX_SUMMARY_LENGTH)
                || (payload.errorCode() != null
                && !validText(payload.errorCode(), MAX_ERROR_CODE_LENGTH))) {
            throw invalid("agent step payload is invalid");
        }
    }

    private boolean validText(String value, int maxLength) {
        return value != null && !value.isBlank() && value.length() <= maxLength;
    }

    private EventContractException invalid(String detail) {
        return new EventContractException("Invalid AGENT_STEP event: " + detail);
    }
}
