package io.github.tobehardoo.trippilot.infrastructure.mq;

import io.github.tobehardoo.trippilot.common.EventContractException;
import java.io.IOException;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import org.springframework.stereotype.Component;

@Component
public class AgentResumeCommandParser {

    private static final int MAX_ANSWER_LENGTH = 2000;

    private final ObjectMapper objectMapper;
    private final ObjectReader reader;

    public AgentResumeCommandParser(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.reader = objectMapper.readerFor(AgentResumeCommand.class)
                .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }

    public AgentResumeCommand parse(byte[] body) {
        try {
            JsonNode tree = objectMapper.readTree(body);
            if (tree == null) {
                throw invalid("command body must contain a JSON object");
            }
            validateJsonTypes(tree);
            AgentResumeCommand command = reader.readValue(tree.traverse(objectMapper));
            validate(command);
            return command;
        } catch (IOException exception) {
            throw new EventContractException("Invalid AGENT_RESUME command", exception);
        }
    }

    private void validateJsonTypes(JsonNode command) {
        if (!command.isObject() || !command.path("eventType").isTextual()
                || !command.path("schemaVersion").isIntegralNumber()
                || !command.path("occurredAt").isTextual()) {
            throw invalid("command envelope field types do not match the JSON Schema");
        }
        for (String idField : new String[]{"eventId", "traceId", "tripId", "runId"}) {
            if (!command.path(idField).isTextual()) {
                throw invalid("command envelope field types do not match the JSON Schema");
            }
        }
        JsonNode payload = command.path("payload");
        if (!payload.isObject() || !payload.path("answer").isTextual()) {
            throw invalid("payload field types do not match the JSON Schema");
        }
    }

    private void validate(AgentResumeCommand command) {
        if (!"AGENT_RESUME".equals(command.eventType()) || command.schemaVersion() != 1) {
            throw invalid("unsupported eventType or schemaVersion");
        }
        if (command.eventId() == null || command.traceId() == null || command.tripId() == null
                || command.runId() == null || command.occurredAt() == null
                || command.payload() == null) {
            throw invalid("command envelope fields are required");
        }
        if (!validText(command.payload().answer(), MAX_ANSWER_LENGTH)) {
            throw invalid("resume answer is invalid");
        }
    }

    private boolean validText(String value, int maxLength) {
        return value != null && !value.isBlank() && value.length() <= maxLength;
    }

    private EventContractException invalid(String detail) {
        return new EventContractException("Invalid AGENT_RESUME command: " + detail);
    }
}
