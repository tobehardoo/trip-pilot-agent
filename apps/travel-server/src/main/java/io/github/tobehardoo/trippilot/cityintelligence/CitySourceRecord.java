package io.github.tobehardoo.trippilot.cityintelligence;

import java.time.Instant;
import java.util.UUID;

public record CitySourceRecord(
        UUID id,
        String cityCode,
        String cityName,
        String sourceName,
        String sourceUrl,
        String sourceType,
        String reliabilityLevel,
        boolean enabled,
        String parserStrategy,
        String refreshPolicyJson,
        String reviewStatus,
        String reviewNote,
        UUID reviewedBy,
        Instant reviewedAt,
        int version,
        Instant createdAt,
        Instant updatedAt
) {
}
