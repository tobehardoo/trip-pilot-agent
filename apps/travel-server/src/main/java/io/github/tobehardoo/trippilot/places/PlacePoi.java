package io.github.tobehardoo.trippilot.places;

import java.math.BigDecimal;

/**
 * A structured point of interest as returned by the AMap Web Service and
 * persisted inside the trip constraint JSONB. Coordinates must always be
 * provided together.
 */
public record PlacePoi(
        String name,
        String providerPoiId,
        String fullAddress,
        BigDecimal longitude,
        BigDecimal latitude,
        String city,
        String district
) {
}
