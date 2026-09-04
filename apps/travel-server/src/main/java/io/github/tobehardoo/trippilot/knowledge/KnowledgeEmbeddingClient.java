package io.github.tobehardoo.trippilot.knowledge;

import java.time.Duration;
import java.util.List;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.ResourceAccessException;

/**
 * 批量获取文本向量。调用 agent-service 的 {@code /internal/v1/embeddings}：
 * DashScope（真实语义模型）优先，未配置则退化为 demo 特征哈希。
 */
@Service
public class KnowledgeEmbeddingClient {

    private final RestClient restClient;

    public KnowledgeEmbeddingClient(
            RestClient.Builder builder,
            @Value("${app.agent.base-url}") String baseUrl,
            @Value("${app.agent.internal-token}") String internalToken
    ) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(3));
        factory.setReadTimeout(Duration.ofSeconds(60));
        this.restClient = builder
                .requestFactory(factory)
                .baseUrl(baseUrl)
                .defaultHeader("X-Internal-Token", internalToken)
                .build();
    }

    /** 对文本批量嵌入，返回 (model, dimensions, vectors)。 */
    public EmbeddingBatch embed(List<String> texts) {
        EmbeddingsRequest request = new EmbeddingsRequest(texts);
        try {
            EmbeddingsResponse response = restClient.post()
                    .uri("/internal/v1/embeddings")
                    .body(request)
                    .retrieve()
                    .body(EmbeddingsResponse.class);
            if (response == null || response.embeddings() == null) {
                throw new IllegalStateException("embedding service returned an empty response");
            }
            if (response.embeddings().size() != texts.size()) {
                throw new IllegalStateException("embedding count mismatch");
            }
            for (List<Double> vector : response.embeddings()) {
                if (vector == null || vector.isEmpty()) {
                    throw new IllegalStateException("embedding vector is empty");
                }
            }
            return new EmbeddingBatch(response.model(), response.dimensions(), response.embeddings());
        } catch (RestClientResponseException exception) {
            throw new IllegalStateException(
                    "embedding service rejected request: " + exception.getResponseBodyAsString(), exception);
        } catch (ResourceAccessException exception) {
            throw new IllegalStateException("embedding service is unavailable", exception);
        }
    }

    public record EmbeddingsRequest(List<String> texts) {
    }

    public record EmbeddingsResponse(String model, int dimensions, List<List<Double>> embeddings) {
    }

    public record EmbeddingBatch(String model, int dimensions, List<List<Double>> vectors) {
    }
}