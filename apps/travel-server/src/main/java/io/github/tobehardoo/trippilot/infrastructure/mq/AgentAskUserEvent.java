package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

public record AgentAskUserEvent(
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
            String question,
            List<String> options,
            String expectedType
    ) {
    }
}
