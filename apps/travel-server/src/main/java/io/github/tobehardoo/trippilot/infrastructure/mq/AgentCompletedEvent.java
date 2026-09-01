package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.time.OffsetDateTime;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;

public record AgentCompletedEvent(
        String eventType,
        int schemaVersion,
        UUID eventId,
        UUID traceId,
        UUID tripId,
        UUID runId,
        OffsetDateTime occurredAt,
        Payload payload
) {
    public record Payload(String summary, JsonNode itinerary, JsonNode slots) {
    }
}
