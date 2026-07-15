package io.github.tobehardoo.trippilot.messaging;

import java.io.IOException;
import java.math.BigDecimal;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import org.springframework.stereotype.Component;

@Component
public class PlanningCompletedEventParser {

    private static final BigDecimal MAX_PERSISTED_MONEY = new BigDecimal("9999999999.99");

    private final ObjectReader reader;
    private final ObjectMapper objectMapper;

    public PlanningCompletedEventParser(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.reader = objectMapper.readerFor(PlanningCompletedEvent.class)
                .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }

    public PlanningCompletedEvent parse(byte[] body) {
        try {
            JsonNode tree = objectMapper.readTree(body);
            if (tree == null) {
                throw invalid("event body must contain a JSON object");
            }
            validateJsonTypes(tree);
            PlanningCompletedEvent event = reader.readValue(tree.traverse(objectMapper));
            validate(event);
            return event;
        } catch (IOException exception) {
            throw new PlanningEventContractException("Invalid PLANNING_COMPLETED event", exception);
        }
    }

    private void validateJsonTypes(JsonNode event) {
        if (!event.isObject() || !event.path("eventType").isTextual()
                || !event.path("schemaVersion").isIntegralNumber()
                || !event.path("occurredAt").isTextual()) {
            throw invalid("event field types do not match the JSON Schema");
        }
        for (String idField : new String[]{"eventId", "traceId", "taskId", "tripId", "runId"}) {
            if (!event.path(idField).isTextual()) {
                throw invalid("event field types do not match the JSON Schema");
            }
        }
        JsonNode payload = event.path("payload");
        JsonNode itinerary = payload.path("itinerary");
        JsonNode days = itinerary.path("days");
        if (!payload.isObject() || !payload.path("provider").isTextual()
                || !itinerary.isObject() || !itinerary.path("title").isTextual()
                || !itinerary.path("estimatedTotalCost").isNumber() || !days.isArray()) {
            throw invalid("payload field types do not match the JSON Schema");
        }
        for (JsonNode day : days) {
            JsonNode activities = day.path("activities");
            if (!day.isObject() || !day.path("date").isTextual() || !activities.isArray()) {
                throw invalid("day field types do not match the JSON Schema");
            }
            for (JsonNode activity : activities) {
                if (!activity.isObject() || !activity.path("title").isTextual()
                        || !activity.path("startTime").isTextual()
                        || !activity.path("endTime").isTextual()
                        || !activity.path("estimatedCost").isNumber()
                        || !activity.path("source").isTextual()) {
                    throw invalid("activity field types do not match the JSON Schema");
                }
            }
        }
    }

    private void validate(PlanningCompletedEvent event) {
        if (!"PLANNING_COMPLETED".equals(event.eventType()) || event.schemaVersion() != 1) {
            throw invalid("unsupported eventType or schemaVersion");
        }
        if (event.eventId() == null || event.traceId() == null || event.taskId() == null
                || event.tripId() == null || event.runId() == null || event.occurredAt() == null) {
            throw invalid("event envelope fields are required");
        }
        if (event.payload() == null || !"DEMO".equals(event.payload().provider())
                || event.payload().itinerary() == null) {
            throw invalid("supported payload is required");
        }
        PlanningCompletedEvent.Itinerary itinerary = event.payload().itinerary();
        if (!validText(itinerary.title(), 200)) {
            throw invalid("itinerary title must contain 1 to 200 characters");
        }
        if (itinerary.days() == null || itinerary.days().isEmpty()) {
            throw invalid("itinerary days must not be empty");
        }
        if (!isPersistableMoney(itinerary.estimatedTotalCost())) {
            throw invalid("estimatedTotalCost must fit NUMERIC(12,2)");
        }
        for (PlanningCompletedEvent.Day day : itinerary.days()) {
            validateDay(day);
        }
    }

    private void validateDay(PlanningCompletedEvent.Day day) {
        if (day == null || day.date() == null || day.activities() == null
                || day.activities().isEmpty()) {
            throw invalid("each itinerary day requires activities");
        }
        java.time.OffsetDateTime previousEnd = null;
        for (PlanningCompletedEvent.Activity activity : day.activities()) {
            if (activity == null || !validText(activity.title(), 200)
                    || activity.startTime() == null || activity.endTime() == null
                    || !isPersistableMoney(activity.estimatedCost())
                    || !"DEMO".equals(activity.source())) {
                throw invalid("activity fields are invalid");
            }
            if (!activity.endTime().isAfter(activity.startTime())) {
                throw invalid("activity endTime must be after startTime");
            }
            if (previousEnd != null && activity.startTime().isBefore(previousEnd)) {
                throw invalid("activities must be ordered without overlap");
            }
            previousEnd = activity.endTime();
        }
    }

    private boolean validText(String value, int maxLength) {
        return value != null && !value.isBlank() && value.length() <= maxLength;
    }

    private boolean isPersistableMoney(BigDecimal value) {
        return value != null
                && value.signum() >= 0
                && value.compareTo(MAX_PERSISTED_MONEY) <= 0
                && value.stripTrailingZeros().scale() <= 2;
    }

    private PlanningEventContractException invalid(String detail) {
        return new PlanningEventContractException("Invalid PLANNING_COMPLETED event: " + detail);
    }
}
