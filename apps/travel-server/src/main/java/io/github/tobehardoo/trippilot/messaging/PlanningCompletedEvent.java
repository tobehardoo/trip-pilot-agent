package io.github.tobehardoo.trippilot.messaging;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

public record PlanningCompletedEvent(
        String eventType,
        int schemaVersion,
        UUID eventId,
        UUID traceId,
        UUID taskId,
        UUID tripId,
        UUID runId,
        OffsetDateTime occurredAt,
        Payload payload
) {
    public record Payload(String provider, Itinerary itinerary) {
    }

    public record Itinerary(String title, List<Day> days, BigDecimal estimatedTotalCost) {
    }

    public record Day(LocalDate date, List<Activity> activities) {
    }

    public record Activity(
            String title,
            OffsetDateTime startTime,
            OffsetDateTime endTime,
            BigDecimal estimatedCost,
            String source,
            String providerPoiId,
            Coordinates coordinates,
            String address
    ) {
    }

    public record Coordinates(BigDecimal longitude, BigDecimal latitude) {
    }
}
