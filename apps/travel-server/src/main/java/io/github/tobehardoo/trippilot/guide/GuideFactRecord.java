package io.github.tobehardoo.trippilot.guide;

import java.time.Instant;
import java.util.UUID;

public record GuideFactRecord(
        UUID id,
        UUID guideImportId,
        String category,
        String statement,
        String evidence,
        double confidence,
        Instant observedAt,
        Instant expiresAt
) {
}
