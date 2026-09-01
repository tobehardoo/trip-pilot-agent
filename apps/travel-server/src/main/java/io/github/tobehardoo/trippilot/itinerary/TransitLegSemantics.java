package io.github.tobehardoo.trippilot.itinerary;

import java.math.BigDecimal;
import java.math.RoundingMode;

/** Stable presentation and provenance derived only from persisted leg facts. */
public final class TransitLegSemantics {

    public static final int TAXI_WAIT_SECONDS = 300;

    private TransitLegSemantics() {
    }

    public static BigDecimal taxiFare(int distanceMeters) {
        if (distanceMeters < 0) {
            throw new IllegalArgumentException("Taxi distance cannot be negative");
        }
        return BigDecimal.valueOf(distanceMeters)
                .multiply(new BigDecimal("2.6"))
                .divide(BigDecimal.valueOf(1000), 2, RoundingMode.HALF_UP)
                .add(new BigDecimal("12.00"))
                .setScale(2, RoundingMode.HALF_UP);
    }

    public static Presentation present(
            String mode,
            int durationSeconds,
            String provider,
            boolean estimated,
            BigDecimal estimatedCost
    ) {
        String normalizedMode = mode == null ? "UNKNOWN" : mode;
        int waitSeconds = "TAXI".equals(normalizedMode) ? TAXI_WAIT_SECONDS : 0;
        if (durationSeconds < waitSeconds) {
            throw new IllegalStateException("Stored TAXI duration is shorter than its wait time");
        }
        String modeLabel = switch (normalizedMode) {
            case "WALKING" -> "步行";
            case "TRANSIT" -> "公交/地铁";
            case "DRIVING", "TAXI" -> "打车";
            default -> normalizedMode;
        };
        String costSource = switch (normalizedMode) {
            case "TAXI", "WALKING" -> "RULE_ESTIMATE";
            default -> {
                if (estimatedCost == null) {
                    yield "UNKNOWN";
                }
                if ("DEMO".equals(provider) || estimated) {
                    yield "DEMO";
                }
                yield "PROVIDER";
            }
        };
        String costMeaning = switch (normalizedMode) {
            case "DRIVING" -> "ROAD_TOLL";
            case "TAXI" -> "TAXI_FARE_ESTIMATE";
            case "TRANSIT" -> "TRANSIT_FARE";
            case "WALKING" -> "NONE";
            default -> "UNKNOWN";
        };
        BigDecimal displayCost = "DRIVING".equals(normalizedMode) ? null : estimatedCost;
        return new Presentation(
                modeLabel,
                durationSeconds - waitSeconds,
                waitSeconds,
                costSource,
                costMeaning,
                displayCost
        );
    }

    public record Presentation(
            String modeLabel,
            int routeDurationSeconds,
            int waitSeconds,
            String costSource,
            String costMeaning,
            BigDecimal displayCost
    ) {
    }
}
