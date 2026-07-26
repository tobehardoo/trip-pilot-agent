package io.github.tobehardoo.trippilot.guide;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

public interface GuideIntelligenceClient {

    FetchedGuide fetch(GuideImportRequest request);

    record FetchedGuide(
            String sourceType,
            String sourceUrl,
            String finalUrl,
            String sourceHost,
            String title,
            String excerpt,
            String contentHash,
            Instant fetchedAt,
            List<FetchedFact> facts
    ) {
    }

    record FetchedFact(
            String category,
            String statement,
            String evidence,
            double confidence,
            LocalDate effectiveDate,
            Instant observedAt,
            Instant expiresAt
    ) {
    }
}
