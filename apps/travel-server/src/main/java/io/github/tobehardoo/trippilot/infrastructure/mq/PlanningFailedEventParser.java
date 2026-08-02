package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.io.IOException;
import java.util.Set;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import org.springframework.stereotype.Component;

@Component
public class PlanningFailedEventParser {

    private static final Set<String> V2_CATEGORIES = Set.of(
            "CONFIGURATION_ERROR", "AUTHENTICATION_ERROR", "PERMISSION_DENIED",
            "QUOTA_EXCEEDED", "RATE_LIMITED", "TIMEOUT", "NETWORK_ERROR",
            "PROVIDER_UNAVAILABLE", "INVALID_REQUEST", "NO_RESULT",
            "UNSUPPORTED_MODE", "MALFORMED_RESPONSE", "DATA_QUALITY_ERROR",
            "PROVIDER_ADAPTER_ERROR", "PLANNING_INFEASIBLE", "INTERNAL_ERROR"
    );
    private static final Set<String> PROVIDERS = Set.of("AMAP", "DEMO", "PLANNER");
    private static final Set<String> OPERATIONS = Set.of(
            "CONFIGURATION", "PLANNING", "REPLANNING", "POI_SEARCH", "ROUTE"
    );

    private final ObjectMapper objectMapper;
    private final ObjectReader v1Reader;
    private final ObjectReader v2Reader;

    public PlanningFailedEventParser(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.v1Reader = objectMapper.readerFor(PlanningFailedEvent.class)
                .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
        this.v2Reader = objectMapper.readerFor(PlanningFailedEvent.class)
                .without(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }

    public PlanningFailedEvent parse(byte[] body) {
        try {
            JsonNode root = objectMapper.readTree(body);
            int version = root.path("schemaVersion").asInt(-1);
            if (version != 1 && version != 2) {
                throw invalid("unsupported schemaVersion");
            }
            if (version == 2) {
                validateV2JsonTypes(root.path("payload"));
            }
            PlanningFailedEvent event = (version == 1 ? v1Reader : v2Reader)
                    .readValue(root);
            validateEnvelope(event);
            if (version == 1) {
                validateV1(event.payload());
            } else {
                validateV2(event.payload());
            }
            return event;
        } catch (PlanningEventContractException exception) {
            throw exception;
        } catch (IOException exception) {
            throw new PlanningEventContractException("Invalid PLANNING_FAILED event", exception);
        }
    }

    private void validateEnvelope(PlanningFailedEvent event) {
        if (event == null || !"PLANNING_FAILED".equals(event.eventType())
                || (event.schemaVersion() != 1 && event.schemaVersion() != 2)
                || event.eventId() == null || event.traceId() == null
                || event.taskId() == null || event.tripId() == null
                || event.runId() == null || event.occurredAt() == null
                || event.payload() == null) {
            throw invalid("failure envelope is incomplete");
        }
    }

    private void validateV1(PlanningFailedEvent.Payload payload) {
        if (!"FAILED".equals(payload.status())
                || !"NO_FEASIBLE_ITINERARY".equals(payload.errorCode())
                || !bounded(payload.message(), 300)
                || payload.conflicts().isEmpty() || payload.conflicts().size() > 20
                || payload.relaxationSuggestions().size() > 20) {
            throw invalid("v1 failure payload is invalid");
        }
        validateActions(payload);
    }

    private void validateV2(PlanningFailedEvent.Payload payload) {
        if (!"FAILED".equals(payload.status())
                || !bounded(payload.errorCode(), 60)
                || !V2_CATEGORIES.contains(payload.errorCategory())
                || !PROVIDERS.contains(payload.provider())
                || !OPERATIONS.contains(payload.operation())
                || payload.retryCount() < 0 || payload.retryCount() > 10
                || payload.fallbackSucceeded() && !payload.fallbackAttempted()
                || !bounded(payload.safeMessage(), 300)
                || payload.safeProviderCode() != null
                && !bounded(payload.safeProviderCode(), 60)
                || payload.causeType() != null && !bounded(payload.causeType(), 60)
                || payload.conflicts().size() > 20
                || payload.relaxationSuggestions().size() > 20
                || "PLANNING_INFEASIBLE".equals(payload.errorCategory())
                && payload.conflicts().isEmpty()) {
            throw invalid("v2 failure payload is invalid");
        }
        validateActions(payload);
    }

    private void validateActions(PlanningFailedEvent.Payload payload) {
        for (PlanningFailedEvent.Conflict conflict : payload.conflicts()) {
            if (conflict == null || !bounded(conflict.code(), 60)
                    || !bounded(conflict.message(), 300)
                    || conflict.affected().isEmpty() || conflict.affected().size() > 30
                    || conflict.affected().stream().anyMatch(value -> !bounded(value, 120))) {
                throw invalid("failure conflict is invalid");
            }
        }
        for (PlanningFailedEvent.Relaxation relaxation : payload.relaxationSuggestions()) {
            if (relaxation == null || !bounded(relaxation.code(), 60)
                    || !bounded(relaxation.message(), 300)) {
                throw invalid("failure relaxation is invalid");
            }
        }
    }

    private void validateV2JsonTypes(JsonNode payload) {
        for (String field : Set.of(
                "status", "errorCode", "errorCategory", "provider", "operation",
                "retryable", "retryCount", "fallbackAttempted", "fallbackSucceeded",
                "safeMessage", "conflicts", "relaxationSuggestions"
        )) {
            if (!payload.has(field) || payload.get(field).isNull()) {
                throw invalid("v2 field is missing: " + field);
            }
        }
        if (!payload.isObject()
                || !payload.path("status").isTextual()
                || !payload.path("errorCode").isTextual()
                || !payload.path("errorCategory").isTextual()
                || !payload.path("provider").isTextual()
                || !payload.path("operation").isTextual()
                || !payload.path("retryable").isBoolean()
                || !payload.path("retryCount").isIntegralNumber()
                || !payload.path("fallbackAttempted").isBoolean()
                || !payload.path("fallbackSucceeded").isBoolean()
                || !payload.path("safeMessage").isTextual()
                || !payload.path("conflicts").isArray()
                || !payload.path("relaxationSuggestions").isArray()
                || payload.has("safeProviderCode")
                && !payload.path("safeProviderCode").isNull()
                && !payload.path("safeProviderCode").isTextual()
                || payload.has("causeType")
                && !payload.path("causeType").isNull()
                && !payload.path("causeType").isTextual()) {
            throw invalid("v2 field types do not match the JSON Schema");
        }
    }

    private boolean bounded(String value, int maxLength) {
        return value != null && !value.isBlank() && value.length() <= maxLength;
    }

    private PlanningEventContractException invalid(String message) {
        return new PlanningEventContractException("Invalid PLANNING_FAILED event: " + message);
    }
}
