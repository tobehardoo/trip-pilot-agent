package io.github.tobehardoo.trippilot.trip;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.UUID;

import org.apache.ibatis.annotations.AutomapConstructor;

public record TripSnapshotRecord(
        UUID id,
        UUID ownerId,
        String title,
        String destination,
        LocalDate startDate,
        LocalDate endDate,
        String status,
        int version,
        Instant createdAt,
        Instant updatedAt,
        Instant archivedAt,
        BigDecimal budgetAmount,
        int travelers,
        String travelerType,
        String pace,
        String preferencesJson,
        String fixedSchedulesJson,
        String arrivalJson,
        String departureJson,
        String accommodationJson,
        String mustVisitPlacesJson,
        String avoidPlacesJson,
        String mustVisitPlaceRefsJson,
        String avoidPlaceRefsJson,
        String mealWindowsJson,
        String mobilityLevel,
        int schemaVersion,
        String regionRefJson,
        OffsetDateTime arrivalAt,
        OffsetDateTime departureAt
) {
    @AutomapConstructor
    public TripSnapshotRecord {
    }

    public TripSnapshotRecord(
            UUID id, UUID ownerId, String title, String destination,
            LocalDate startDate, LocalDate endDate, String status, int version,
            Instant createdAt, Instant updatedAt, Instant archivedAt,
            BigDecimal budgetAmount, int travelers, String travelerType, String pace,
            String preferencesJson, String fixedSchedulesJson, String arrivalJson,
            String departureJson, String accommodationJson, String mustVisitPlacesJson,
            String avoidPlacesJson, String mealWindowsJson, String mobilityLevel,
            int schemaVersion
    ) {
        this(id, ownerId, title, destination, startDate, endDate, status, version,
                createdAt, updatedAt, archivedAt, budgetAmount, travelers, travelerType,
                pace, preferencesJson, fixedSchedulesJson, arrivalJson, departureJson,
                accommodationJson, mustVisitPlacesJson, avoidPlacesJson, null, null,
                mealWindowsJson, mobilityLevel, schemaVersion, null, null, null);
    }
}
