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
            ProviderProvenance providerProvenance,
            PlanEvaluation evaluation,
            io.github.tobehardoo.trippilot.feasibility.FeasibilityReport feasibilityReport,
            boolean hasBlocker
    ) {
        public Payload(
                String provider,
                Itinerary itinerary,
                KnowledgeEvidence knowledge
        ) {
            this(provider, itinerary, knowledge, List.of(), null, null, null, false);
        }

        public Payload(
                String provider,
                Itinerary itinerary,
                KnowledgeEvidence knowledge,
                List<FactImpact> factImpacts
        ) {
            this(provider, itinerary, knowledge, factImpacts, null, null, null, false);
        }

        public Payload(
                String provider,
                Itinerary itinerary,
                KnowledgeEvidence knowledge,
                List<FactImpact> factImpacts,
                ProviderProvenance providerProvenance
        ) {
            this(provider, itinerary, knowledge, factImpacts, providerProvenance, null, null, false);
        }

        public Payload {
            factImpacts = factImpacts == null ? List.of() : List.copyOf(factImpacts);
        }
    }

    public record Itinerary(String title, List<Day> days, BigDecimal estimatedTotalCost,
                            AccommodationData accommodation) {
    }

    /** Optional accommodation resolution status carried for display. */
    public record AccommodationData(String status, String placeName) {
    }

    public record Day(
            LocalDate date,
            List<Activity> activities,
            List<TransitLeg> transitLegs,
            String dayType
    ) {
        public Day(LocalDate date, List<Activity> activities, List<TransitLeg> transitLegs) {
            this(date, activities, transitLegs, null);
        }

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
            String address,
            String typeCode,
            String typeName,
            String kind,
            Boolean timeFixed,
            Boolean locked,
            String costSource
    ) {
        public Activity {
            costSource = costSource == null || costSource.isBlank() ? "UNKNOWN" : costSource;
        }

        public Activity(
                UUID activityId,
                String title,
                OffsetDateTime startTime,
                OffsetDateTime endTime,
                BigDecimal estimatedCost,
                String source,
                String providerPoiId,
                Coordinates coordinates,
                String address,
                String typeCode,
                String typeName
        ) {
            this(activityId, title, startTime, endTime, estimatedCost, source,
                    providerPoiId, coordinates, address, typeCode, typeName,
                    null, null, null, null);
        }

        public Activity(
                UUID activityId, String title, OffsetDateTime startTime,
                OffsetDateTime endTime, BigDecimal estimatedCost, String source,
                String providerPoiId, Coordinates coordinates, String address,
                String typeCode, String typeName, String kind, Boolean timeFixed
        ) {
            this(activityId, title, startTime, endTime, estimatedCost, source,
                    providerPoiId, coordinates, address, typeCode, typeName,
                    kind, timeFixed, null, null);
        }

        public Activity(
                UUID activityId, String title, OffsetDateTime startTime,
                OffsetDateTime endTime, BigDecimal estimatedCost, String source,
                String providerPoiId, Coordinates coordinates, String address,
                String typeCode, String typeName, String kind,
                Boolean timeFixed, Boolean locked
        ) {
            this(activityId, title, startTime, endTime, estimatedCost, source,
                    providerPoiId, coordinates, address, typeCode, typeName,
                    kind, timeFixed, locked, null);
        }
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
            String costSource,
            Boolean locked
    ) {
        public TransitLeg {
            polyline = polyline == null ? List.of() : List.copyOf(polyline);
            costSource = costSource == null || costSource.isBlank() ? "UNKNOWN" : costSource;
        }


        public TransitLeg(
                UUID transitId, int fromActivityIndex, int toActivityIndex,
                String mode, int distanceMeters, int durationSeconds,
                String provider, boolean estimated, List<Coordinates> polyline,
                BigDecimal estimatedCost, String costSource
        ) {
            this(transitId, fromActivityIndex, toActivityIndex, mode,
                    distanceMeters, durationSeconds, provider, estimated,
                    polyline, estimatedCost, costSource, null);
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

    public record PlanEvaluation(
            int schemaVersion,
            String evaluatorVersion,
            boolean feasible,
            int overallScore,
            EvaluationDimensions dimensions,
            List<EvaluationWarning> warnings,
            List<DecisionExplanation> decisions,
            String summary,
            OffsetDateTime evaluatedAt
    ) {
        public PlanEvaluation {
            warnings = warnings == null ? List.of() : List.copyOf(warnings);
            decisions = decisions == null ? List.of() : List.copyOf(decisions);
        }
    }

    public record EvaluationDimensions(
            int constraintSatisfaction,
            int timeFeasibility,
            Integer budgetFit,
            int routeEfficiency,
            Integer interestMatch
    ) {
    }

    public record EvaluationWarning(
            String code,
            String severity,
            String message,
            Integer dayIndex,
            String entityType,
            UUID entityId,
            String metricKey,
            Double actualValue,
            Double threshold
    ) {
    }

    public record DecisionExplanation(
            String subjectType,
            UUID subjectId,
            String summary,
            List<String> reasonCodes,
            List<String> reasons,
            List<UUID> constraintRefs,
            List<EvaluationEvidence> evidence,
            Integer dayIndex
    ) {
        public DecisionExplanation {
            reasonCodes = reasonCodes == null ? List.of() : List.copyOf(reasonCodes);
            reasons = reasons == null ? List.of() : List.copyOf(reasons);
            constraintRefs = constraintRefs == null ? List.of() : List.copyOf(constraintRefs);
            evidence = evidence == null ? List.of() : List.copyOf(evidence);
        }
    }

    public record EvaluationEvidence(
            String key,
            String label,
            String value
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
