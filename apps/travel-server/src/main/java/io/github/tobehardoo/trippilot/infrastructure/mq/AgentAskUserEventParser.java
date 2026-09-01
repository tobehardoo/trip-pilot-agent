package io.github.tobehardoo.trippilot.infrastructure.mq;

import io.github.tobehardoo.trippilot.common.EventContractException;
import java.io.IOException;
import java.util.List;
import java.util.Set;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import org.springframework.stereotype.Component;

@Component
public class AgentAskUserEventParser {

    private static final Set<String> SUPPORTED_EXPECTED_TYPES =
            Set.of("TEXT", "NUMBER", "DATE", "CHOICE");
    private static final int MAX_OPTIONS = 10;
    private static final int MAX_QUESTION_LENGTH = 300;
    private static final int MAX_OPTION_LENGTH = 60;

    private final ObjectMapper objectMapper;
    private final ObjectReader reader;

    public AgentAskUserEventParser(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.reader = objectMapper.readerFor(AgentAskUserEvent.class)
                .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }

    public AgentAskUserEvent parse(byte[] body) {
        try {
            JsonNode tree = objectMapper.readTree(body);
            if (tree == null) {
                throw invalid("event body must contain a JSON object");
            }
            validateJsonTypes(tree);
            AgentAskUserEvent event = reader.readValue(tree.traverse(objectMapper));
            validate(event);
            return event;
        } catch (IOException exception) {
            throw new EventContractException("Invalid AGENT_ASK_USER event", exception);
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
        if (!payload.isObject() || !payload.path("question").isTextual()) {
            throw invalid("payload field types do not match the JSON Schema");
        }
        JsonNode options = payload.path("options");
        if (!options.isMissingNode() && !options.isNull() && !options.isArray()) {
            throw invalid("payload field types do not match the JSON Schema");
        }
        JsonNode expectedType = payload.path("expectedType");
        if (!expectedType.isMissingNode() && !expectedType.isNull()
                && !expectedType.isTextual()) {
            throw invalid("payload field types do not match the JSON Schema");
        }
    }

    private void validate(AgentAskUserEvent event) {
        if (!"AGENT_ASK_USER".equals(event.eventType()) || event.schemaVersion() != 1) {
            throw invalid("unsupported eventType or schemaVersion");
        }
        if (event.eventId() == null || event.traceId() == null || event.tripId() == null
                || event.runId() == null || event.occurredAt() == null
                || event.payload() == null) {
            throw invalid("event envelope fields are required");
        }
        AgentAskUserEvent.Payload payload = event.payload();
        if (!validText(payload.question(), MAX_QUESTION_LENGTH)) {
            throw invalid("ask_user question is invalid");
        }
        List<String> options = payload.options();
        if (options != null && (options.size() > MAX_OPTIONS
                || options.stream().anyMatch(option -> !validText(option, MAX_OPTION_LENGTH)))) {
            throw invalid("ask_user options are invalid");
        }
        if (payload.expectedType() != null
                && !SUPPORTED_EXPECTED_TYPES.contains(payload.expectedType())) {
            throw invalid("ask_user expectedType is invalid");
        }
    }

    private boolean validText(String value, int maxLength) {
        return value != null && !value.isBlank() && value.length() <= maxLength;
    }

    private EventContractException invalid(String detail) {
        return new EventContractException("Invalid AGENT_ASK_USER event: " + detail);
    }
}
