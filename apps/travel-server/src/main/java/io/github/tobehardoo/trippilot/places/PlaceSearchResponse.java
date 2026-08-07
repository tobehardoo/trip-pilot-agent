package io.github.tobehardoo.trippilot.places;

import java.util.List;

/**
 * Search result envelope. {@code status} is {@code AVAILABLE} when the AMap
 * provider answered (possibly with zero matches) and {@code UNAVAILABLE} when
 * the provider could not be reached, so the client can offer "暂不设置酒店"
 * instead of silently trusting free text.
 */
public record PlaceSearchResponse(List<PlacePoi> results, String status) {

    public static PlaceSearchResponse available(List<PlacePoi> results) {
        return new PlaceSearchResponse(List.copyOf(results), "AVAILABLE");
    }

    public static PlaceSearchResponse unavailable() {
        return new PlaceSearchResponse(List.of(), "UNAVAILABLE");
    }
}
