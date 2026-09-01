package io.github.tobehardoo.trippilot.guide;

import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

public record GuideFactRecord(
        UUID id,
        UUID guideImportId,
        String category,
        String statement,
        String evidence,
        double confidence,
        LocalDate effectiveDate,
        Instant observedAt,
        Instant expiresAt
) {
}
