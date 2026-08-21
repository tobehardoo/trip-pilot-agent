package io.github.tobehardoo.trippilot.route;

import java.time.Duration;

import io.github.tobehardoo.trippilot.common.ApiException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

@Service
public class HttpAgentRouteClient implements AgentRouteClient {

    private final RestClient restClient;
    private final String internalToken;

    @Autowired
    public HttpAgentRouteClient(
            RestClient.Builder builder,
            @Value("${app.agent.base-url}") String baseUrl,
            @Value("${app.agent.internal-token}") String internalToken
    ) {
        this(builder.requestFactory(requestFactory()).baseUrl(baseUrl).build(), internalToken);
    }

    HttpAgentRouteClient(RestClient restClient, String internalToken) {
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
    public AgentRouteDtos.RouteFacts route(AgentRouteDtos.RouteRequest request) {
        return post("/internal/v1/routes", request, AgentRouteDtos.RouteFacts.class);
    }

    @Override
    public AgentRouteDtos.Recommendation recommend(AgentRouteDtos.RecommendRequest request) {
        return post(
                "/internal/v1/routes/recommend", request,
                AgentRouteDtos.Recommendation.class);
    }

    private <T> T post(String path, Object request, Class<T> responseType) {
        try {
            T response = restClient.post()
                    .uri(path)
                    .header("X-Internal-Token", internalToken)
                    .body(request)
                    .retrieve()
                    .body(responseType);
            if (response == null) {
                throw unavailable();
            }
            return response;
        } catch (RestClientResponseException | ResourceAccessException exception) {
            throw unavailable();
        }
    }

    private static ApiException unavailable() {
        return new ApiException(
                HttpStatus.BAD_GATEWAY,
                "ROUTE_PROVIDER_UNAVAILABLE",
                "Route service is temporarily unavailable");
    }
}
