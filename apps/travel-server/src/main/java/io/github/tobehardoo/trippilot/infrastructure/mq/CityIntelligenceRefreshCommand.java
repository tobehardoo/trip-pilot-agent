package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

public record CityIntelligenceRefreshCommand(
        String eventType,
        int schemaVersion,
        UUID eventId,
        UUID refreshId,
        UUID tripId,
        Instant occurredAt,
        Payload payload
) {
    public record Payload(
            String city,
            String cityCode,
            LocalDate startDate,
            LocalDate endDate,
            List<UUID> sourceIds,
            List<String> requiredCategories,
            UUID idempotencyKey
    ) {
        public Payload {
            sourceIds = sourceIds == null ? List.of() : List.copyOf(sourceIds);
            requiredCategories = requiredCategories == null
                    ? List.of()
                    : List.copyOf(requiredCategories);
        }
    }
}
