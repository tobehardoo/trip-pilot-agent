package io.github.tobehardoo.trippilot.guide;

import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

public record GuidePlanningEvidenceRecord(
        UUID guideImportId,
        UUID factId,
        String category,
        String statement,
        String evidence,
        String sourceType,
        String sourceUrl,
        String sourceHost,
        String sourceTitle,
        double confidence,
        LocalDate effectiveDate,
        Instant observedAt,
        Instant expiresAt
) {
}
