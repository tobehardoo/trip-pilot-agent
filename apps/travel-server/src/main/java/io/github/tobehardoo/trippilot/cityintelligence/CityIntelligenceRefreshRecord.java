package io.github.tobehardoo.trippilot.cityintelligence;

import java.time.Instant;
import java.util.UUID;

public record CityIntelligenceRefreshRecord(
        UUID id,
        UUID tripId,
        String cityCode,
        UUID idempotencyKey,
        String status,
        String requestedCategoriesJson,
        String providerDiagnosticsJson,
        int attemptCount,
        Instant startedAt,
        Instant completedAt,
        String errorCode,
        String errorMessage,
        int version,
        Instant createdAt,
        Instant updatedAt
) {
}
