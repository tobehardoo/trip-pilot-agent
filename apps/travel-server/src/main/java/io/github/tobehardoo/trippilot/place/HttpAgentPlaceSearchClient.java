package io.github.tobehardoo.trippilot.place;

import java.time.Duration;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceSearchRequest;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceSearchResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

/**
 * RestClient proxy to the agent service's protected place search endpoint.
 *
 * Mirrors {@code HttpGuideIntelligenceClient}: short connect timeout, the
 * internal token header, and safe error mapping that never leaks upstream
 * provider details or keys.
 */
@Service
public class HttpAgentPlaceSearchClient implements AgentPlaceSearchClient {

    private final RestClient restClient;
    private final String internalToken;

    @Autowired
    public HttpAgentPlaceSearchClient(
            RestClient.Builder builder,
            @Value("${app.agent.base-url}") String baseUrl,
            @Value("${app.agent.internal-token}") String internalToken
    ) {
        this(builder.requestFactory(requestFactory()).baseUrl(baseUrl).build(), internalToken);
    }

    /** Test seam: inject a pre-built client (e.g. mock-server-bound). */
    HttpAgentPlaceSearchClient(RestClient restClient, String internalToken) {
        this.restClient = restClient;
        this.internalToken = internalToken;
    }

    private static SimpleClientHttpRequestFactory requestFactory() {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofSeconds(3));
        requestFactory.setReadTimeout(Duration.ofSeconds(15));
        return requestFactory;
    }

    @Override
    public PlaceSearchResponse search(PlaceSearchRequest request) {
        try {
            PlaceSearchResponse response = restClient.post()
                    .uri("/internal/v1/places/search")
                    .header("X-Internal-Token", internalToken)
                    .body(request)
                    .retrieve()
                    .body(PlaceSearchResponse.class);
            if (response == null) {
                throw unavailable("Agent place search returned an empty response");
            }
            return response;
        } catch (RestClientResponseException exception) {
            throw unavailable("Agent place search is unavailable");
        } catch (ResourceAccessException exception) {
            throw unavailable("Agent place search is unavailable");
        }
    }

    private ApiException unavailable(String message) {
        return new ApiException(HttpStatus.BAD_GATEWAY, "PLACE_SEARCH_UNAVAILABLE", message);
    }
}
