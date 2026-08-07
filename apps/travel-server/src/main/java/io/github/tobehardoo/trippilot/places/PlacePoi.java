package io.github.tobehardoo.trippilot.places;

import java.math.BigDecimal;

/**
 * A structured point of interest as returned by the AMap Web Service and
 * persisted inside the trip constraint JSONB. Coordinates must always be
 * provided together. {@code categoryName} is the specific AMap type label
 * (e.g. "高铁站") and {@code categoryCode} the AMap type code (e.g. "150302");
 * both let the backend re-validate a saved anchor against its scene.
 */
public record PlacePoi(
        String name,
        String providerPoiId,
        String fullAddress,
        BigDecimal longitude,
        BigDecimal latitude,
        String city,
        String district,
        String districtCode,
        String categoryName,
        String categoryCode
) {
}
