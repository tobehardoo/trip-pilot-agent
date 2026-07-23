package io.github.tobehardoo.trippilot.trip;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

public record TripConstraintRecord(
        UUID tripId,
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
        int schemaVersion,
        Instant updatedAt
) {
}
