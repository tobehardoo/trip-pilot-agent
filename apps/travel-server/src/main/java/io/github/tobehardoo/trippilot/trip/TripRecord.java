package io.github.tobehardoo.trippilot.trip;

import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

public record TripRecord(
        UUID id,
        UUID ownerId,
        String title,
        String destination,
        LocalDate startDate,
        LocalDate endDate,
        String status,
        int version,
        Instant createdAt,
        Instant updatedAt
) {
}
