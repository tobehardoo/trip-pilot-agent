package io.github.tobehardoo.trippilot.guide;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

public interface GuideIntelligenceClient {

    FetchedGuide fetch(GuideImportRequest request);

    default FetchedGuide fetchRegisteredSource(RegisteredSourceRequest request) {
        throw new UnsupportedOperationException("Registered source import is not supported");
    }

    record RegisteredSourceRequest(
            String sourceUrl,
            String sourceType,
            String sourceName,
            String city
    ) {
    }

    record FetchedGuide(
            String sourceType,
            String sourceUrl,
            String finalUrl,
            String sourceHost,
            String title,
            String excerpt,
            String contentHash,
            Instant fetchedAt,
            List<FetchedFact> facts,
            FetchedNormalizedDocument normalizedDocument,
            List<FetchedTrustedFact> trustedFacts,
            List<FetchedRejectedFact> rejectedFacts,
            List<FetchedMergeDecision> factMergeDecisions,
            FetchedModelExtraction modelExtraction
    ) {
        public FetchedGuide(
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
            this(
                    sourceType,
                    sourceUrl,
                    finalUrl,
                    sourceHost,
                    title,
                    excerpt,
                    contentHash,
                    fetchedAt,
                    facts,
                    null,
                    List.of(),
                    List.of(),
                    List.of(),
                    new FetchedModelExtraction(
                            "SKIPPED",
                            0,
                            "MODEL_NOT_RUN",
                            "V1.2-compatible response"
                    )
            );
        }
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

    record FetchedNormalizedDocument(
            String documentId,
            String sourceType,
            String sourceName,
            String sourceUrl,
            String city,
            String title,
            String content,
            Instant fetchedAt,
            String contentHash,
            String encoding,
            String language,
            Map<String, Object> metadata,
            String reliabilityLevel,
            boolean sourceReviewed
    ) {
    }

    record FetchedTrustedFact(
            String factId,
            String documentId,
            String category,
            String statement,
            Map<String, Object> normalizedValue,
            String evidence,
            int evidenceStart,
            int evidenceEnd,
            double confidence,
            LocalDate effectiveDate,
            Instant checkedAt,
            Instant expiresAt,
            String sourceType,
            String sourceName,
            String sourceUrl,
            String reliabilityLevel,
            boolean sourceReviewed,
            boolean hardConstraintEligible
    ) {
    }

    record FetchedRejectionReason(String code, String message) {
    }

    record FetchedRejectedFact(
            String category,
            String statement,
            List<FetchedRejectionReason> reasons
    ) {
    }

    record FetchedMergeDecision(
            String selectedFactId,
            List<String> conflictFactIds,
            List<String> downgradedFactIds,
            String reason,
            boolean needsManualReview
    ) {
    }

    record FetchedModelExtraction(
            String status,
            int attempts,
            String failureCode,
            String failureReason
    ) {
    }
}
