package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

public record PlanningTaskCompletionRecord(
        UUID id,
        UUID tripId,
        String status,
        int baselineTripVersion,
        UUID traceId,
        int taskVersion,
        String constraintSnapshotJson,
        int currentTripVersion,
        LocalDate tripStartDate,
        LocalDate tripEndDate,
        Instant createdAt
) {
}
