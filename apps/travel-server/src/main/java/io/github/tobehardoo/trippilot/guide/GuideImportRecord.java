package io.github.tobehardoo.trippilot.guide;

import java.time.Instant;
import java.util.UUID;

public record GuideImportRecord(
        UUID id,
        UUID tripId,
        String sourceUrl,
        String finalUrl,
        String sourceHost,
        String title,
        String excerpt,
        String contentHash,
        Instant fetchedAt,
        Instant createdAt
) {
}
