package io.github.tobehardoo.trippilot.messaging;

import java.time.Instant;
import java.util.UUID;

public record OutboxEventRecord(
        UUID id,
        String aggregateType,
        UUID aggregateId,
        String eventType,
        String routingKey,
        String payloadJson,
        String status,
        int retryCount,
        Instant nextAttemptAt,
        String lastError,
        Instant createdAt,
        Instant sentAt
) {
}
