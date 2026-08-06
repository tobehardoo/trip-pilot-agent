package io.github.tobehardoo.trippilot.places;

import java.util.List;

/**
 * Server-side structured place search. Implementations must never leak the
 * provider key to the browser and must fail closed rather than inventing
 * trusted free-text places.
 */
public interface PlaceSearchClient {

    /**
     * Searches structured POIs restricted to {@code city}.
     *
     * @throws PlaceSearchUnavailableException when the provider cannot be
     *         reached after bounded retries
     */
    List<PlacePoi> search(String keyword, String city, int limit);
}
