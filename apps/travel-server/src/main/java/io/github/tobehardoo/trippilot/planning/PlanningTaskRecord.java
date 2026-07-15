package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.util.UUID;

public record PlanningTaskRecord(
        UUID id,
        UUID tripId,
        UUID idempotencyKey,
        String taskType,
        String status,
        int baselineTripVersion,
        UUID traceId,
        int retryCount,
        String errorCode,
        String errorMessage,
        int version,
        Instant createdAt,
        Instant updatedAt
) {
}
