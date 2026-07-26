package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

public record PlanningTaskCompletionRecord(
        UUID id,
        UUID tripId,
        String taskType,
        String status,
        int baselineTripVersion,
        UUID baselineItineraryVersionId,
        String impactedDatesJson,
        UUID traceId,
        int taskVersion,
        String constraintSnapshotJson,
        int currentTripVersion,
        UUID currentItineraryVersionId,
        LocalDate tripStartDate,
        LocalDate tripEndDate,
        Instant createdAt
) {
}
