package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.time.OffsetDateTime;
import java.util.UUID;

public record AgentRunFinishedEvent(
        String eventType,
        int schemaVersion,
        UUID eventId,
        UUID traceId,
        UUID tripId,
        UUID runId,
        OffsetDateTime occurredAt,
        Payload payload
) {
    public record Payload(
            String status,
            String reasonCode,
            String message
    ) {
    }
}
