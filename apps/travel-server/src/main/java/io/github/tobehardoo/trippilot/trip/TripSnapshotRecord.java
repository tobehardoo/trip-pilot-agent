package io.github.tobehardoo.trippilot.trip;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

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
        String mealWindowsJson,
        String mobilityLevel,
        int schemaVersion
) {
}
