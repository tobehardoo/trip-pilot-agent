package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.util.UUID;

public record PlanningTaskRecord(
        UUID id,
        UUID tripId,
        UUID idempotencyKey,
        String taskType,
        String status,
        int baselineTripVersion,
        UUID baselineItineraryVersionId,
        String impactedDatesJson,
        String constraintSnapshotJson,
        String guideEvidenceSnapshotJson,
        UUID traceId,
        int retryCount,
        String errorCode,
        String errorMessage,
        int version,
        Instant createdAt,
        Instant updatedAt,
        String candidateType,
        UUID candidateSourceVersionId,
        String candidateRequestHash,
        String changedDatesJson
) {
    @org.apache.ibatis.annotations.AutomapConstructor
    public PlanningTaskRecord {
    }

    public PlanningTaskRecord(
            UUID id, UUID tripId, UUID idempotencyKey, String taskType,
            String status, int baselineTripVersion, UUID baselineItineraryVersionId,
            String impactedDatesJson, String constraintSnapshotJson,
            String guideEvidenceSnapshotJson, UUID traceId, int retryCount,
            String errorCode, String errorMessage, int version,
            Instant createdAt, Instant updatedAt
    ) {
        this(id, tripId, idempotencyKey, taskType, status, baselineTripVersion,
                baselineItineraryVersionId, impactedDatesJson, constraintSnapshotJson,
                guideEvidenceSnapshotJson, traceId, retryCount, errorCode,
                errorMessage, version, createdAt, updatedAt, null, null, null, null);
    }
}
