package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

public record PlanningCompletedEvent(
        String eventType,
        int schemaVersion,
        UUID eventId,
        UUID traceId,
        UUID taskId,
        UUID tripId,
        UUID runId,
        OffsetDateTime occurredAt,
        Payload payload
) {
    public record Payload(
            String provider,
            Itinerary itinerary,
            KnowledgeEvidence knowledge,
            List<FactImpact> factImpacts,
            ProviderProvenance providerProvenance
    ) {
        public Payload(
                String provider,
                Itinerary itinerary,
                KnowledgeEvidence knowledge
        ) {
            this(provider, itinerary, knowledge, List.of(), null);
        }

        public Payload(
                String provider,
                Itinerary itinerary,
                KnowledgeEvidence knowledge,
                List<FactImpact> factImpacts
        ) {
            this(provider, itinerary, knowledge, factImpacts, null);
        }

        public Payload {
            factImpacts = factImpacts == null ? List.of() : List.copyOf(factImpacts);
        }
    }

    public record Itinerary(String title, List<Day> days, BigDecimal estimatedTotalCost) {
    }

    public record Day(LocalDate date, List<Activity> activities, List<TransitLeg> transitLegs) {
        public Day {
            transitLegs = transitLegs == null ? List.of() : List.copyOf(transitLegs);
        }
    }

    public record Activity(
            UUID activityId,
            String title,
            OffsetDateTime startTime,
            OffsetDateTime endTime,
            BigDecimal estimatedCost,
            String source,
            String providerPoiId,
            Coordinates coordinates,
            String address
    ) {
    }

    public record Coordinates(BigDecimal longitude, BigDecimal latitude) {
    }

    public record TransitLeg(
            UUID transitId,
            int fromActivityIndex,
            int toActivityIndex,
            String mode,
            int distanceMeters,
            int durationSeconds,
            String provider,
            boolean estimated,
            List<Coordinates> polyline,
            BigDecimal estimatedCost,
            String costSource
    ) {
        public TransitLeg {
            polyline = polyline == null ? List.of() : List.copyOf(polyline);
            costSource = costSource == null || costSource.isBlank() ? "UNKNOWN" : costSource;
        }
    }

    public enum ProviderExecutionMode {
        DEMO_ONLY,
        REAL_ONLY,
        REAL_WITH_EXPLICIT_FALLBACK
    }

    public enum ProviderSource {
        AMAP,
        DEMO
    }

    public enum ProviderOperation {
        PLANNING,
        REPLANNING,
        ROUTE
    }

    public enum ProviderErrorCategory {
        QUOTA_EXCEEDED,
        RATE_LIMITED,
        TIMEOUT,
        NETWORK_ERROR,
        PROVIDER_UNAVAILABLE,
        MALFORMED_RESPONSE
    }

    public record ProviderProvenance(
            ProviderExecutionMode requestedProviderMode,
            ProviderSource primaryProvider,
            List<ProviderSource> actualProviders,
            boolean fallbackAttempted,
            boolean fallbackSucceeded,
            String fallbackReason,
            List<FallbackOperation> fallbackOperations
    ) {
        public ProviderProvenance {
            actualProviders = actualProviders == null
                    ? List.of() : List.copyOf(actualProviders);
            fallbackOperations = fallbackOperations == null
                    ? List.of() : List.copyOf(fallbackOperations);
        }
    }

    public record FallbackOperation(
            ProviderOperation operation,
            UUID transitId,
            UUID fromActivityId,
            UUID toActivityId,
            ProviderExecutionMode requestedMode,
            ProviderSource actualProvider,
            ProviderErrorCategory errorCategory,
            String errorCode,
            int retryCount
    ) {
    }

    public record KnowledgeEvidence(
            String status,
            String query,
            List<KnowledgeCitation> citations,
            KnowledgeFreshness freshness,
            String message
    ) {
        public KnowledgeEvidence {
            citations = citations == null ? List.of() : List.copyOf(citations);
        }
    }

    public record KnowledgeCitation(
            String documentId,
            int documentVersion,
            String chunkId,
            int chunkIndex,
            String title,
            String sourceUrl,
            String sourceName,
            OffsetDateTime collectedAt,
            String reliabilityLevel,
            double similarity
    ) {
    }

    public record KnowledgeFreshness(
            String status,
            OffsetDateTime checkedAt,
            String staleReason
    ) {
    }

    public record FactImpact(
            String factId,
            String category,
            LocalDate date,
            String effect,
            String targetPoiId,
            String targetName,
            String reason,
            String sourceName,
            String sourceType,
            String sourceUrl,
            String reliabilityLevel,
            OffsetDateTime checkedAt,
            String evidence,
            boolean stale,
            boolean conflicted,
            boolean refreshFailed
    ) {
    }
}
