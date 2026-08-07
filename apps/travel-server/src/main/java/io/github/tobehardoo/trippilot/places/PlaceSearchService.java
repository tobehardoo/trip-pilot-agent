package io.github.tobehardoo.trippilot.places;

import io.github.tobehardoo.trippilot.common.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

/**
 * Orchestrates structured place search: input guards, a bounded per-minute
 * rate limit, and fail-closed behavior when the provider or key is
 * unavailable. The provider key never leaves the server.
 */
@Service
public class PlaceSearchService {

    private final PlaceSearchClient client;
    private final PlaceSearchProperties properties;
    private final FixedWindowRateLimiter rateLimiter;

    public PlaceSearchService(
            PlaceSearchClient client,
            PlaceSearchProperties properties,
            FixedWindowRateLimiter rateLimiter
    ) {
        this.client = client;
        this.properties = properties;
        this.rateLimiter = rateLimiter;
    }

    public PlaceSearchResponse search(String keyword, String city) {
        String normalizedKeyword = normalize(keyword);
        String normalizedCity = normalize(city);
        if (normalizedKeyword.length() > properties.keywordMaxLength()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "PLACE_SEARCH_INVALID",
                    "Search keyword must not exceed " + properties.keywordMaxLength() + " characters");
        }
        if (normalizedCity.length() > 60) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "PLACE_SEARCH_INVALID",
                    "City must not exceed 60 characters");
        }
        if (!rateLimiter.tryAcquire(properties.rateLimitPerMinute())) {
            throw new ApiException(HttpStatus.TOO_MANY_REQUESTS, "PLACE_SEARCH_RATE_LIMITED",
                    "Place search is temporarily rate limited; retry shortly");
        }
        if (properties.amapKey() == null || properties.amapKey().isBlank()) {
            return PlaceSearchResponse.unavailable();
        }
        try {
            return PlaceSearchResponse.available(
                    client.search(normalizedKeyword, normalizedCity, properties.maxResults())
            );
        } catch (PlaceSearchUnavailableException exception) {
            return PlaceSearchResponse.unavailable();
        }
    }

    private static String normalize(String value) {
        return value == null ? "" : value.trim();
    }
}
