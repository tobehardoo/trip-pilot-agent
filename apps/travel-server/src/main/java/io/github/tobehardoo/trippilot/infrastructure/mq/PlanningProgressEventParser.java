package io.github.tobehardoo.trippilot.infrastructure.mq;

import io.github.tobehardoo.trippilot.common.EventContractException;
import java.io.IOException;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import org.springframework.stereotype.Component;

@Component
public class PlanningProgressEventParser {

    private static final Set<String> SUPPORTED_STAGES = Set.of(
            "TASK_ACCEPTED",
            "CONTEXT_VALIDATING",
            "CITY_FACTS_LOADING",
            "POI_RECALLING",
            "CANDIDATES_RANKING",
            "ROUTES_CALCULATING",
            "CONSTRAINTS_SOLVING",
            "REPAIRING",
            "KNOWLEDGE_RETRIEVING",
            "RESULT_EXPLAINING",
            "RESULT_PUBLISHING",
            "RESULT_PERSISTING"
    );

    private final ObjectMapper objectMapper;
    private final ObjectReader reader;

    public PlanningProgressEventParser(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.reader = objectMapper.readerFor(PlanningProgressEvent.class)
                .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }

    public PlanningProgressEvent parse(byte[] body) {
        try {
            JsonNode tree = objectMapper.readTree(body);
            if (tree == null) {
                throw invalid("event body must contain a JSON object");
            }
            validateJsonTypes(tree);
            PlanningProgressEvent event = reader.readValue(tree.traverse(objectMapper));
            validate(event);
            return event;
        } catch (IOException exception) {
            throw new EventContractException("Invalid PLANNING_PROGRESS event", exception);
        }
    }

    private void validateJsonTypes(JsonNode event) {
        if (!event.isObject() || !event.path("eventType").isTextual()
                || !event.path("schemaVersion").isIntegralNumber()
                || !event.path("occurredAt").isTextual()) {
            throw invalid("event envelope field types do not match the JSON Schema");
        }
        for (String idField : new String[]{"eventId", "traceId", "taskId", "tripId"}) {
            if (!event.path(idField).isTextual()) {
                throw invalid("event envelope field types do not match the JSON Schema");
            }
        }
        JsonNode payload = event.path("payload");
        if (!payload.isObject() || !payload.path("stage").isTextual()
                || !payload.path("sequence").isIntegralNumber()
                || !payload.path("progress").isIntegralNumber()
                || !payload.path("message").isTextual()
                || !payload.path("statistics").isObject()) {
            throw invalid("payload field types do not match the JSON Schema");
        }
        payload.path("statistics").fields().forEachRemaining(entry -> {
            if (!entry.getValue().isIntegralNumber()) {
                throw invalid("progress statistics must use integer values");
            }
        });
    }

    private void validate(PlanningProgressEvent event) {
        if (!"PLANNING_PROGRESS".equals(event.eventType())
                || (event.schemaVersion() != 1 && event.schemaVersion() != 2)) {
            throw invalid("unsupported eventType or schemaVersion");
        }
        if (event.eventId() == null || event.traceId() == null || event.taskId() == null
                || event.tripId() == null || event.occurredAt() == null || event.payload() == null) {
            throw invalid("event envelope fields are required");
        }
        PlanningProgressEvent.Payload payload = event.payload();
        if (!SUPPORTED_STAGES.contains(payload.stage())
                || payload.sequence() < 1 || payload.sequence() > 100
                || payload.progress() < 0 || payload.progress() > 100
                || !validText(payload.message(), 300)
                || payload.statistics().size() > 20) {
            throw invalid("progress payload is invalid");
        }
        for (Map.Entry<String, Integer> statistic : payload.statistics().entrySet()) {
            if (!validText(statistic.getKey(), 60) || statistic.getValue() == null
                    || statistic.getValue() < 0) {
                throw invalid("progress statistics are invalid");
            }
        }
        validateRepairProgress(event.schemaVersion(), payload);
    }

    private void validateRepairProgress(
            int schemaVersion, PlanningProgressEvent.Payload payload
    ) {
        if (!"REPAIRING".equals(payload.stage())) {
            return;
        }
        if (schemaVersion != 2) {
            throw invalid("REPAIRING requires schemaVersion 2");
        }
        Integer attemptIndex = payload.statistics().get("attemptIndex");
        Integer actionCount = payload.statistics().get("actionCount");
        if (attemptIndex == null || attemptIndex < 1 || attemptIndex > 3
                || actionCount == null || actionCount < 1 || actionCount > 16) {
            throw invalid("REPAIRING statistics are invalid");
        }
    }

    private boolean validText(String value, int maxLength) {
        return value != null && !value.isBlank() && value.length() <= maxLength;
    }

    private EventContractException invalid(String detail) {
        return new EventContractException("Invalid PLANNING_PROGRESS event: " + detail);
    }
}
