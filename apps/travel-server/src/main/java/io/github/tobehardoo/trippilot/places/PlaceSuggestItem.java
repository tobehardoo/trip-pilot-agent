package io.github.tobehardoo.trippilot.places;

import java.math.BigDecimal;

/**
 * One entry in the mixed autocomplete list. {@code POI} is the only type that
 * can be saved as a travel anchor; {@code REGION} adjusts the search scope and
 * {@code SUGGESTION} only fills the keyword for a follow-up search.
 */
public record PlaceSuggestItem(
        String itemType,
        String provider,
        String providerPoiId,
        String name,
        String category,
        String provinceCode,
        String cityCode,
        String districtCode,
        String districtName,
        String fullAddress,
        BigDecimal longitude,
        BigDecimal latitude
) {

    public static PlaceSuggestItem poi(String provider, String providerPoiId, String name, String category,
                                       String provinceCode, String cityCode, String districtCode,
                                       String districtName, String fullAddress,
                                       BigDecimal longitude, BigDecimal latitude) {
        return new PlaceSuggestItem("POI", provider, providerPoiId, name, category,
                provinceCode, cityCode, districtCode, districtName, fullAddress, longitude, latitude);
    }

    public static PlaceSuggestItem region(String name, String category,
                                          String provinceCode, String cityCode) {
        return new PlaceSuggestItem("REGION", null, null, name, category,
                provinceCode, cityCode, null, null, null, null, null);
    }
}
