package io.github.tobehardoo.trippilot.guide;

import java.time.Instant;
import java.util.UUID;

public record GuidePlanningEvidenceRecord(
        UUID guideImportId,
        UUID factId,
        String category,
        String statement,
        String evidence,
        String sourceUrl,
        String sourceHost,
        String sourceTitle,
        double confidence,
        Instant observedAt,
        Instant expiresAt
) {
}
