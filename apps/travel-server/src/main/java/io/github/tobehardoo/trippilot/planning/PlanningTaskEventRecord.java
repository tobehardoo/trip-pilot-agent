package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.util.UUID;

public record PlanningTaskEventRecord(
        Long id,
        UUID eventId,
        UUID taskId,
        String eventType,
        int schemaVersion,
        String payloadJson,
        Instant createdAt
) {
}
