package io.github.tobehardoo.trippilot.guide;

import java.time.Duration;
import java.util.Map;

import io.github.tobehardoo.trippilot.common.ApiException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.http.client.SimpleClientHttpRequestFactory;

@Service
public class HttpGuideIntelligenceClient implements GuideIntelligenceClient {

    private final RestClient restClient;
    private final String internalToken;

    public HttpGuideIntelligenceClient(
            RestClient.Builder builder,
            @Value("${app.agent.base-url}") String baseUrl,
            @Value("${app.agent.internal-token}") String internalToken
    ) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofSeconds(3));
        requestFactory.setReadTimeout(Duration.ofSeconds(15));
        this.restClient = builder
                .requestFactory(requestFactory)
                .baseUrl(baseUrl)
                .build();
        this.internalToken = internalToken;
    }

    @Override
    public FetchedGuide fetch(String sourceUrl) {
        try {
            FetchedGuide response = restClient.post()
                    .uri("/internal/v1/guide-imports")
                    .header("X-Internal-Token", internalToken)
                    .body(Map.of("sourceUrl", sourceUrl))
                    .retrieve()
                    .body(FetchedGuide.class);
            if (response == null) {
                throw unavailable("Guide intelligence service returned an empty response");
            }
            return response;
        } catch (RestClientResponseException exception) {
            if (exception.getStatusCode().is4xxClientError()
                    && exception.getStatusCode().value() != 401) {
                throw new ApiException(
                        HttpStatus.UNPROCESSABLE_ENTITY,
                        "GUIDE_IMPORT_REJECTED",
                        "The public guide could not be imported"
                );
            }
            throw unavailable("Guide intelligence service is unavailable");
        } catch (ResourceAccessException exception) {
            throw unavailable("Guide intelligence service is unavailable");
        }
    }

    private ApiException unavailable(String message) {
        return new ApiException(HttpStatus.BAD_GATEWAY, "GUIDE_SERVICE_UNAVAILABLE", message);
    }
}
