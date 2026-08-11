package io.github.tobehardoo.trippilot.itinerary;

import java.time.Instant;
import java.util.UUID;

/**
 * Persisted feasibility report for an itinerary version (schema v9 completions).
 *
 * Columns mirror V33__create_itinerary_feasibility_report.sql.  Only VERIFIED
 * reports are persisted; the DB enforces the status/schema/fingerprint
 * constraints and that the report JSON matches the row columns.
 */
public record ItineraryFeasibilityReportRecord(
        UUID itineraryVersionId,
        UUID reportId,
        int schemaVersion,
        String validatorVersion,
        String itineraryFingerprint,
        String status,
        Instant validatedAt,
        String reportJson
) {
}
