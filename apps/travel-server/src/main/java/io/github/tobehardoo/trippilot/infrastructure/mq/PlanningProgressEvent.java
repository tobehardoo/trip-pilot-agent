package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;

public record PlanningProgressEvent(
        String eventType,
        int schemaVersion,
        UUID eventId,
        UUID traceId,
        UUID taskId,
        UUID tripId,
        OffsetDateTime occurredAt,
        Payload payload
) {
    public record Payload(
            String stage,
            int sequence,
            int progress,
            String message,
            Map<String, Integer> statistics
    ) {
        public Payload {
            statistics = statistics == null ? Map.of() : Map.copyOf(statistics);
        }
    }
}
