package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

public record PlanningContextSnapshotRecord(
        UUID id,
        UUID tripId,
        UUID planningTaskId,
        UUID cityIntelligenceSnapshotId,
        int schemaVersion,
        String city,
        LocalDate travelStartDate,
        LocalDate travelEndDate,
        Instant generatedAt,
        boolean stale,
        String sourcesJson,
        String factsJson,
        String conflictsJson,
        String excludedFactsJson,
        String diagnosticsJson,
        String contentDigest
) {
}
