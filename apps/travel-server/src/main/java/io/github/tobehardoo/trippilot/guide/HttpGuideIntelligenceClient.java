package io.github.tobehardoo.trippilot.guide;

import java.time.Duration;
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
            @Value("${app.agent.internal-token}") String internalToken,
            @Value("${app.agent.read-timeout-seconds:60}") long readTimeoutSeconds
    ) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofSeconds(3));
        requestFactory.setReadTimeout(Duration.ofSeconds(readTimeoutSeconds));
        this.restClient = builder
                .requestFactory(requestFactory)
                .baseUrl(baseUrl)
                .build();
        this.internalToken = internalToken;
    }

    @Override
    public FetchedGuide fetch(GuideImportRequest request) {
        return post(request);
    }

    @Override
    public FetchedGuide fetchRegisteredSource(RegisteredSourceRequest request) {
        return post(request);
    }

    private FetchedGuide post(Object request) {
        try {
            FetchedGuide response = restClient.post()
                    .uri("/internal/v1/guide-imports")
                    .header("X-Internal-Token", internalToken)
                    .body(request)
                    .retrieve()
                    .body(FetchedGuide.class);
            if (response == null) {
                throw unavailable("Guide intelligence service returned an empty response");
            }
            return response;
        } catch (RestClientResponseException exception) {
            if (exception.getStatusCode().is4xxClientError()
                    && exception.getStatusCode().value() != 401) {
                throw rejectionFor(exception.getResponseBodyAsString());
            }
            throw unavailable("Guide intelligence service is unavailable");
        } catch (ResourceAccessException exception) {
            throw unavailable("Guide intelligence service is unavailable");
        }
    }

    /**
     * The agent-service reports OCR and validation failures as 422 with a
     * stable "CODE: message" detail; surface dedicated codes so the web UI can
     * give actionable guidance instead of a generic rejection.
     */
    static ApiException rejectionFor(String responseBody) {
        String detail = responseBody == null ? "" : responseBody;
        if (detail.contains("OCR_NOT_CONFIGURED")) {
            return new ApiException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "GUIDE_OCR_NOT_CONFIGURED",
                    "图片识别未配置：请在服务端配置视觉识别模型后重试，或改用粘贴正文导入。"
            );
        }
        if (detail.contains("OCR_TIMEOUT")) {
            return new ApiException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "GUIDE_OCR_TIMEOUT",
                    "图片识别超时，请减少图片数量后重试，或改用粘贴正文导入。"
            );
        }
        if (detail.contains("OCR_NO_TEXT")
                || detail.contains("OCR_TEXT_TOO_SHORT")
                || detail.contains("OCR_FAILED")) {
            return new ApiException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "GUIDE_OCR_FAILED",
                    "未能从图片中识别出可用的攻略文字，请确认截图清晰并包含正文后重试。"
            );
        }
        if (detail.contains("IMAGE_")) {
            return new ApiException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "GUIDE_IMAGE_INVALID",
                    "图片不符合要求：仅支持 PNG、JPEG、WEBP，单张不超过 5 MB、一次不超过 5 张。"
            );
        }
        return new ApiException(
                HttpStatus.UNPROCESSABLE_ENTITY,
                "GUIDE_IMPORT_REJECTED",
                "The public guide could not be imported"
        );
    }

    private ApiException unavailable(String message) {
        return new ApiException(HttpStatus.BAD_GATEWAY, "GUIDE_SERVICE_UNAVAILABLE", message);
    }
}
