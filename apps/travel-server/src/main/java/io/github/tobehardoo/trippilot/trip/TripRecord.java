package io.github.tobehardoo.trippilot.trip;

import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.UUID;

import org.apache.ibatis.annotations.AutomapConstructor;

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
        Instant updatedAt,
        Instant archivedAt,
        String regionRefJson,
        OffsetDateTime arrivalAt,
        OffsetDateTime departureAt
) {
    @AutomapConstructor
    public TripRecord {
    }

    public TripRecord(
            UUID id, UUID ownerId, String title, String destination,
            LocalDate startDate, LocalDate endDate, String status, int version,
            Instant createdAt, Instant updatedAt, Instant archivedAt
    ) {
        this(id, ownerId, title, destination, startDate, endDate, status, version,
                createdAt, updatedAt, archivedAt, null, null, null);
    }
}
