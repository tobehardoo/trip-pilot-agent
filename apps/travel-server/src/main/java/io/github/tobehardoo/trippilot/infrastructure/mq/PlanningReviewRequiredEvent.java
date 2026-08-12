package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.databind.JsonNode;

/**
 * PLANNING_REVIEW_REQUIRED event (schema v1).
 *
 * Produced when the hard validator could not verify the candidate itinerary.
 * Shares the v9 itinerary/knowledge/provenance structure with
 * {@link PlanningCompletedEvent}, but carries no evaluation and its
 * feasibility report must be UNVERIFIED or NEEDS_REPAIR.
 */
public record PlanningReviewRequiredEvent(
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
            String status,
            String provider,
            PlanningCompletedEvent.Itinerary itinerary,
            PlanningCompletedEvent.KnowledgeEvidence knowledge,
            List<PlanningCompletedEvent.FactImpact> factImpacts,
            PlanningCompletedEvent.ProviderProvenance providerProvenance,
            io.github.tobehardoo.trippilot.feasibility.FeasibilityReport feasibilityReport,
            @JsonIgnore JsonNode validatedItineraryJson
    ) {
        public Payload {
            factImpacts = factImpacts == null ? List.of() : List.copyOf(factImpacts);
        }

        /**
         * Compatibility constructor for callers that do not carry the raw
         * validated itinerary snapshot (no snapshot available).  The parser
         * uses the full constructor to attach the validated raw itinerary.
         */
        public Payload(
                String status,
                String provider,
                PlanningCompletedEvent.Itinerary itinerary,
                PlanningCompletedEvent.KnowledgeEvidence knowledge,
                List<PlanningCompletedEvent.FactImpact> factImpacts,
                PlanningCompletedEvent.ProviderProvenance providerProvenance,
                io.github.tobehardoo.trippilot.feasibility.FeasibilityReport feasibilityReport
        ) {
            this(status, provider, itinerary, knowledge, factImpacts, providerProvenance,
                    feasibilityReport, null);
        }

        /**
         * The raw itinerary JSON captured by the parser after schema,
         * semantic and fingerprint validation.  This is Java-internal
         * metadata: it is never part of the wire schema, never serialised
         * into task events, and is what the review service persists as
         * candidateItinerary so the read model can re-verify the report
         * fingerprint against a byte-identical tree.  A defensive deep copy
         * is returned so callers cannot mutate the internal snapshot.
         */
        public JsonNode validatedItineraryJson() {
            return validatedItineraryJson == null
                    ? null : validatedItineraryJson.deepCopy();
        }
    }
}
