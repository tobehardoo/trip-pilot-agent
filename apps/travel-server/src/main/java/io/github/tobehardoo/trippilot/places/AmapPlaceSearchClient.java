package io.github.tobehardoo.trippilot.places;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * Restricted proxy over the AMap text-search Web Service. The key stays on
 * the server; the client applies one bounded retry for transient failures
 * and a category filter so hotels, rail stations, and airports are found
 * instead of arbitrary places. The {@link RestClient} carries the timeout
 * configured in {@link PlaceSearchConfig}.
 */
@Service
public class AmapPlaceSearchClient implements PlaceSearchClient {

    private static final String ENDPOINT = "https://restapi.amap.com/v3/place/text";
    /**
     * Hotel (120000), railway station (150302), and airport (150500) POI
     * categories. Keeps results structural instead of free-form.
     */
    private static final String TYPE_FILTER = "120000|150302|150500";
    private static final int MAX_RETRIES = 1;

    private final RestClient restClient;
    private final PlaceSearchProperties properties;

    public AmapPlaceSearchClient(
            @Qualifier("amapPlaceSearchRestClient") RestClient restClient,
            PlaceSearchProperties properties
    ) {
        this.restClient = restClient;
        this.properties = properties;
    }

    @Override
    public List<PlacePoi> search(String keyword, String city, int limit) {
        try {
            return request(keyword, city, limit);
        } catch (RestClientResponseException | ResourceAccessException exception) {
            for (int attempt = 0; attempt < MAX_RETRIES; attempt++) {
                try {
                    return request(keyword, city, limit);
                } catch (RestClientResponseException | ResourceAccessException retryException) {
                    // fall through and fail closed
                }
            }
            throw new PlaceSearchUnavailableException();
        }
    }

    private List<PlacePoi> request(String keyword, String city, int limit) {
        JsonNode body = restClient.get()
                .uri(UriComponentsBuilder.fromHttpUrl(ENDPOINT)
                        .queryParam("key", properties.amapKey())
                        .queryParam("keywords", keyword)
                        .queryParam("city", city)
                        .queryParam("citylimit", "true")
                        .queryParam("offset", limit)
                        .queryParam("types", TYPE_FILTER)
                        .queryParam("extensions", "base")
                        .build().encode().toUri())
                .retrieve()
                .body(JsonNode.class);
        if (body == null || !"1".equals(body.path("status").asText())) {
            throw new PlaceSearchUnavailableException();
        }
        List<PlacePoi> results = new ArrayList<>();
        JsonNode pois = body.path("pois");
        for (JsonNode poi : pois) {
            PlacePoi parsed = toPoi(poi, city);
            if (parsed != null) {
                results.add(parsed);
            }
        }
        return results;
    }

    private PlacePoi toPoi(JsonNode poi, String fallbackCity) {
        String name = poi.path("name").asText(null);
        String id = poi.path("id").asText(null);
        if (name == null || id == null) {
            return null;
        }
        String location = poi.path("location").asText(null);
        BigDecimal longitude = null;
        BigDecimal latitude = null;
        if (location != null && location.contains(",")) {
            String[] parts = location.split(",");
            try {
                longitude = new BigDecimal(parts[0]);
                latitude = new BigDecimal(parts[1]);
            } catch (NumberFormatException exception) {
                longitude = null;
                latitude = null;
            }
        }
        if (longitude == null || latitude == null) {
            return null;
        }
        String cityName = textOrNull(poi.path("cityname"));
        String cityValue = cityName != null ? cityName : fallbackCity;
        return new PlacePoi(
                name,
                id,
                poi.path("address").asText(""),
                longitude,
                latitude,
                cityValue,
                textOrNull(poi.path("adname"))
        );
    }

    /** AMap returns {@code []} for the cityname of municipalities; only a plain string is usable. */
    private static String textOrNull(JsonNode node) {
        if (node == null || !node.isTextual()) {
            return null;
        }
        String value = node.asText().trim();
        return value.isEmpty() ? null : value;
    }
}
