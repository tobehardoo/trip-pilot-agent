package io.github.tobehardoo.trippilot.guide;

import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

public final class TrustedGuideRecords {

    private TrustedGuideRecords() {
    }

    public record NormalizedDocumentRecord(
            UUID guideImportId,
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
            String metadataJson,
            String reliabilityLevel,
            boolean sourceReviewed,
            String modelStatus,
            int modelAttempts,
            String modelFailureCode,
            String modelFailureReason
    ) {
    }

    public record TrustedFactRecord(
            UUID guideImportId,
            String factId,
            String documentId,
            String city,
            String category,
            String statement,
            String normalizedValueJson,
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

    public record RejectedFactRecord(
            UUID id,
            UUID guideImportId,
            String category,
            String statement,
            String reasonsJson
    ) {
    }

    public record FactMergeDecisionRecord(
            UUID id,
            UUID guideImportId,
            String selectedFactId,
            String conflictFactIdsJson,
            String downgradedFactIdsJson,
            String decisionReason,
            boolean needsManualReview
    ) {
    }
}
