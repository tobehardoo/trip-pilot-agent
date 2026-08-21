package io.github.tobehardoo.trippilot.route;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;

public final class AgentRouteDtos {

    private AgentRouteDtos() {
    }

    public record Coordinates(BigDecimal longitude, BigDecimal latitude) {
    }

    public record RouteRequest(
            Coordinates origin,
            Coordinates destination,
            String mode,
            OffsetDateTime departureAt,
            String originPoiId,
            String destinationPoiId,
            String city
    ) {
    }

    public record RecommendRequest(
            Coordinates origin,
            Coordinates destination,
            OffsetDateTime departureAt,
            String originPoiId,
            String destinationPoiId,
            String city,
            String mobilityLevel
    ) {
        public static RecommendRequest from(RouteRequest request, String mobilityLevel) {
            return new RecommendRequest(
                    request.origin(), request.destination(), request.departureAt(),
                    request.originPoiId(), request.destinationPoiId(), request.city(),
                    mobilityLevel);
        }
    }

    public record RouteFacts(
            String mode,
            int distanceMeters,
            int durationSeconds,
            List<Coordinates> polyline,
            BigDecimal estimatedCost,
            Integer walkingDistanceMeters,
            Integer transferCount,
            String provider,
            boolean estimated,
            boolean cached,
            Instant fetchedAt
    ) {
        public RouteFacts {
            polyline = polyline == null ? List.of() : List.copyOf(polyline);
        }
    }

    public record Recommendation(
            String selectedMode,
            String reason,
            int providerCallsUsed,
            boolean budgetDegraded,
            RouteFacts route
    ) {
    }
}
