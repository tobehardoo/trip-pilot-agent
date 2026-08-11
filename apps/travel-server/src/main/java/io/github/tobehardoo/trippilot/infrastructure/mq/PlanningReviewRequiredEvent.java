package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

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
            io.github.tobehardoo.trippilot.feasibility.FeasibilityReport feasibilityReport
    ) {
        public Payload {
            factImpacts = factImpacts == null ? List.of() : List.copyOf(factImpacts);
        }
    }
}
