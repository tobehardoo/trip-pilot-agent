package io.github.tobehardoo.trippilot.agentdialog;

import java.time.Duration;
import java.util.List;
import java.util.Map;

import io.github.tobehardoo.trippilot.common.ApiException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

/**
 * Synchronous proxy to the agent-service dialog endpoint (Plan B v0.1).
 *
 * Conversation state lives in the agent service; travel-server only forwards
 * trip facts (destination/dates) as read-only context — Java stays the
 * business-fact authority and no dialog state is persisted on this side.
 */
@Service
public class HttpAgentDialogClient {

    private final RestClient restClient;
    private final String internalToken;

    public HttpAgentDialogClient(
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

    public AgentDialogReply dialogue(AgentDialogCommand command) {
        return post(command, AgentDialogReply.class);
    }

    /** Creation-mode chat: no trip scope, keyed by a client-generated session. */
    public AgentDialogReply createDialogue(AgentCreateDialogCommand command) {
        return post(command, AgentDialogReply.class);
    }    /** Confirmed-slot projection the trip will be created from. */
    public AgentConfirmedSlots confirmedCreation(String sessionId) {
        try {
            AgentConfirmedSlots slots = restClient.get()
                    .uri("/internal/v1/agent/dialogue/confirmed/{sessionId}", sessionId)
                    .header("X-Internal-Token", internalToken)
                    .retrieve()
                    .body(AgentConfirmedSlots.class);
            if (slots == null) {
                throw unavailable("Agent dialog service returned an empty response");
            }
            return slots;
        } catch (RestClientResponseException exception) {
            throw new ApiException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "AGENT_TRIP_NOT_READY",
                    "对话还没确认完整约束，先在助手里完成确认再创建行程。"
            );
        } catch (ResourceAccessException exception) {
            throw unavailable("Agent dialog service is unavailable");
        }
    }

    private <T> T post(Object body, Class<T> responseType) {
        try {
            T response = restClient.post()
                    .uri("/internal/v1/agent/dialogue")
                    .header("X-Internal-Token", internalToken)
                    .body(body)
                    .retrieve()
                    .body(responseType);
            if (response == null) {
                throw unavailable("Agent dialog service returned an empty response");
            }
            return response;
        } catch (RestClientResponseException exception) {
            throw unavailable("Agent dialog service rejected the request");
        } catch (ResourceAccessException exception) {
            throw unavailable("Agent dialog service is unavailable");
        }
    }

    private ApiException unavailable(String message) {
        return new ApiException(HttpStatus.BAD_GATEWAY, "AGENT_DIALOGUE_UNAVAILABLE", message);
    }

    record AgentDialogCommand(
            String tripId,
            String message,
            CardOption option,
            boolean reset,
            TripContext tripContext
    ) {
    }

    /**
     * Creation-mode dialog command. {@code tripContext} carries the composer's
     * Required Context (destination + dates) so the dialog seeds them as
     * read-only TRIP facts instead of re-asking; null starts a blank slate.
     */
    public record AgentCreateDialogCommand(
            String sessionId,
            String message,
            CardOption option,
            boolean reset,
            TripContext tripContext
    ) {
    }

    public record AgentConfirmedSlots(boolean ready, Map<String, Object> confirmed) {
    }

    public record CardOption(String action, String label, Object value) {
    }

    public record TripContext(String destination, String startDate, String endDate) {
    }

    public record SlotView(Object value, String state, String source) {
    }

    public record AgentDialogMessage(String role, String text, String kind, List<CardOption> options) {
    }

    public record AgentDialogReply(
            String phase,
            boolean ready,
            List<AgentDialogMessage> messages,
            Map<String, SlotView> slots
    ) {
    }
}
