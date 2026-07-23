package io.github.tobehardoo.trippilot.guide;

import java.time.Instant;
import java.util.List;

public interface GuideIntelligenceClient {

    FetchedGuide fetch(String sourceUrl);

    record FetchedGuide(
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
            Instant observedAt,
            Instant expiresAt
    ) {
    }
}
