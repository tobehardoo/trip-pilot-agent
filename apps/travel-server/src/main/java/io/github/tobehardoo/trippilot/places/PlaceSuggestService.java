package io.github.tobehardoo.trippilot.places;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.trip.RegionCatalog;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

/**
 * Mixed autocomplete for ARRIVAL/DEPARTURE/HOTEL fields: real AMap POIs plus
 * administrative REGION entries from the static catalog. REGION entries are
 * never saved as anchors; they only let the client refine the search scope.
 */
@Service
public class PlaceSuggestService {

    private static final int KEYWORD_MAX = 30;

    private final PlaceSearchClient client;
    private final PlaceSearchProperties properties;
    private final FixedWindowRateLimiter rateLimiter;

    public PlaceSuggestService(
            PlaceSearchClient client,
            PlaceSearchProperties properties,
            FixedWindowRateLimiter rateLimiter
    ) {
        this.client = client;
        this.properties = properties;
        this.rateLimiter = rateLimiter;
    }

    public PlaceSuggestResponse suggest(String keyword, String cityCode, String scene) {
        String normalized = keyword == null ? "" : keyword.trim();
        if (normalized.isEmpty() || normalized.length() > KEYWORD_MAX) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "PLACE_SEARCH_INVALID",
                    "Keyword must be between 1 and " + KEYWORD_MAX + " characters");
        }
        if (cityCode == null || cityCode.isBlank() || !RegionCatalog.hasCity(cityCode)) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "PLACE_SEARCH_INVALID",
                    "A known destination cityCode is required");
        }
        if (!rateLimiter.tryAcquire(properties.rateLimitPerMinute())) {
            throw new ApiException(HttpStatus.TOO_MANY_REQUESTS, "PLACE_SEARCH_RATE_LIMITED",
                    "Place search is temporarily rate limited; retry shortly");
        }
        String cityName = RegionCatalog.cityName(cityCode);
        List<PlaceSuggestItem> items = new ArrayList<>();
        // A suggestion is always actionable: clicking it re-searches the raw
        // keyword. It never carries a POI id so it can never become an anchor.
        items.add(PlaceSuggestItem.suggestion(normalized));
        items.addAll(regionMatches(normalized, cityCode));
        if (properties.amapKey() != null && !properties.amapKey().isBlank()) {
            try {
                for (PlacePoi poi : client.searchScene(normalized, cityName,
                        properties.maxResults(), scene)) {
                    items.add(PlaceSuggestItem.poi(
                            "AMAP", poi.providerPoiId(), poi.name(),
                            poi.categoryName(), poi.categoryCode(),
                            RegionCatalog.provinceOfCity(cityCode), cityCode,
                            poi.districtCode(), poi.district(), poi.fullAddress(),
                            poi.longitude(), poi.latitude()));
                }
            } catch (PlaceSearchUnavailableException ignored) {
                // Autocomplete degrades to region-only entries when AMap is down.
            }
        }
        return new PlaceSuggestResponse(items);
    }

    private static List<PlaceSuggestItem> regionMatches(String keyword, String cityCode) {
        List<PlaceSuggestItem> matches = new ArrayList<>();
        String cityName = RegionCatalog.cityName(cityCode);
        if (cityName != null && contains(keyword, cityName)) {
            matches.add(PlaceSuggestItem.region(cityName, "地级市",
                    RegionCatalog.provinceOfCity(cityCode), cityCode));
        }
        for (String districtName : RegionCatalog.districtsOfCity(cityCode)) {
            if (contains(keyword, districtName)) {
                String districtCode = RegionCatalog.districtCodeOf(districtName, cityCode);
                matches.add(new PlaceSuggestItem(
                        "REGION", null, null, districtName, "区县", null,
                        RegionCatalog.provinceOfCity(cityCode), cityCode,
                        districtCode, districtName, null, null, null));
            }
        }
        return matches;
    }

    private static boolean contains(String keyword, String candidate) {
        if (candidate == null) {
            return false;
        }
        return candidate.contains(keyword) || keyword.contains(candidate);
    }
}
