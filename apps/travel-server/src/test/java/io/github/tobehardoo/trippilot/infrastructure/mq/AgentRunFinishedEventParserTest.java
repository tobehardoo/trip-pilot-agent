package io.github.tobehardoo.trippilot.infrastructure.mq;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.EventContractException;
import io.github.tobehardoo.trippilot.support.AgentEventFixtures;
import org.junit.jupiter.api.Test;

class AgentRunFinishedEventParserTest {

    private final AgentRunFinishedEventParser parser = new AgentRunFinishedEventParser(
            new ObjectMapper().findAndRegisterModules()
    );

    @Test
    void parsesAValidRunFinishedEvent() {
        AgentRunFinishedEvent event = parser.parse(validBody().getBytes(StandardCharsets.UTF_8));
        assertThat(event.eventType()).isEqualTo("AGENT_RUN_FINISHED");
        assertThat(event.schemaVersion()).isEqualTo(1);
        assertThat(event.runId()).hasToString("5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d");
        assertThat(event.payload().status()).isEqualTo("STOPPED");
        assertThat(event.payload().reasonCode()).isEqualTo("CEILING_REACHED");
        assertThat(event.payload().message()).contains("步骤上限");
    }

    @Test
    void acceptsTheSharedCrossLanguageFixture() {
        AgentRunFinishedEvent event = parser.parse(
                AgentEventFixtures.load("agent-run-finished-event-v1", "valid.json")
                        .getBytes(StandardCharsets.UTF_8)
        );
        assertThat(event.payload().status()).isEqualTo("STOPPED");
        assertThat(event.payload().reasonCode()).isEqualTo("CEILING_REACHED");
    }

    @Test
    void parsesAnExpiredTerminal() {
        String body = validBody()
                .replace("\"status\": \"STOPPED\"", "\"status\": \"EXPIRED\"")
                .replace("\"reasonCode\": \"CEILING_REACHED\"", "\"reasonCode\": \"RUN_EXPIRED\"");
        AgentRunFinishedEvent event = parser.parse(body.getBytes(StandardCharsets.UTF_8));
        assertThat(event.payload().status()).isEqualTo("EXPIRED");
        assertThat(event.payload().reasonCode()).isEqualTo("RUN_EXPIRED");
    }

    @Test
    void rejectsAnUnsupportedStatus() {
        String body = validBody().replace("\"status\": \"STOPPED\"", "\"status\": \"PAUSED\"");
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsAnUnsupportedSchemaVersion() {
        String body = validBody().replace("\"schemaVersion\": 1", "\"schemaVersion\": 2");
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsABlankMessage() {
        String body = validBody().replace(
                "\"message\": \"这次处理达到了单轮步骤上限，未能完成你的请求。可以换个说法再试一次。\"",
                "\"message\": \"   \""
        );
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsAnUnknownPayloadField() {
        String body = validBody().replace(
                "\"reasonCode\": \"CEILING_REACHED\"",
                "\"reasonCode\": \"CEILING_REACHED\", \"retryable\": true"
        );
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsANonTextualRunId() {
        String body = validBody().replace(
                "\"runId\": \"5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d\"", "\"runId\": 123"
        );
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    private String validBody() {
        return """
                {
                  "eventType": "AGENT_RUN_FINISHED",
                  "schemaVersion": 1,
                  "eventId": "8c0d1e2f-3a4b-4c5d-8e9f-0a1b2c3d4e5f",
                  "traceId": "1c2d3e4f-0a1b-4c2d-8e3f-4a5b6c7d8e9f",
                  "tripId": "9ee5e831-90f7-4a60-bb8d-fb488aa799ca",
                  "runId": "5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d",
                  "occurredAt": "2026-08-29T08:31:00Z",
                  "payload": {
                    "status": "STOPPED",
                    "reasonCode": "CEILING_REACHED",
                    "message": "这次处理达到了单轮步骤上限，未能完成你的请求。可以换个说法再试一次。"
                  }
                }
                """;
    }
}
