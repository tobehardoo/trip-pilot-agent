package io.github.tobehardoo.trippilot.infrastructure.mq;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.EventContractException;
import io.github.tobehardoo.trippilot.support.AgentEventFixtures;
import org.junit.jupiter.api.Test;

class AgentStepEventParserTest {

    private final AgentStepEventParser parser = new AgentStepEventParser(
            new ObjectMapper().findAndRegisterModules()
    );

    @Test
    void parsesAValidStepEvent() {
        AgentStepEvent event = parser.parse(validBody().getBytes(StandardCharsets.UTF_8));
        assertThat(event.eventType()).isEqualTo("AGENT_STEP");
        assertThat(event.schemaVersion()).isEqualTo(1);
        assertThat(event.runId()).hasToString("5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d");
        assertThat(event.payload().seq()).isZero();
        assertThat(event.payload().tool()).isEqualTo("ask_user");
        assertThat(event.payload().ok()).isTrue();
        assertThat(event.payload().errorCode()).isNull();
    }

    @Test
    void acceptsTheSharedCrossLanguageFixture() {
        AgentStepEvent event = parser.parse(
                AgentEventFixtures.load("agent-step-event-v1", "valid.json")
                        .getBytes(StandardCharsets.UTF_8)
        );
        assertThat(event.payload().tool()).isEqualTo("ask_user");
    }

    @Test
    void parsesAFailedStepWithAnErrorCode() {
        String body = validBody().replace(
                "\"summary\": \"你想去哪个城市？\"",
                "\"summary\": \"地图服务未配置\", \"errorCode\": \"CAPABILITY_MISSING\""
        ).replace("\"ok\": true", "\"ok\": false");
        AgentStepEvent event = parser.parse(body.getBytes(StandardCharsets.UTF_8));
        assertThat(event.payload().ok()).isFalse();
        assertThat(event.payload().summary()).isEqualTo("地图服务未配置");
        assertThat(event.payload().errorCode()).isEqualTo("CAPABILITY_MISSING");
    }

    @Test
    void rejectsAnUnsupportedSchemaVersion() {
        String body = validBody().replace("\"schemaVersion\": 1", "\"schemaVersion\": 2");
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsANegativeSequence() {
        String body = validBody().replace("\"seq\": 0", "\"seq\": -1");
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsABlankSummary() {
        String body = validBody().replace(
                "\"summary\": \"你想去哪个城市？\"", "\"summary\": \"   \""
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
                  "eventType": "AGENT_STEP",
                  "schemaVersion": 1,
                  "eventId": "ad1e2f3a-4b5c-4d6e-8f7a-0b1c2d3e4f5b",
                  "traceId": "1c2d3e4f-0a1b-4c2d-8e3f-4a5b6c7d8e9f",
                  "tripId": "9ee5e831-90f7-4a60-bb8d-fb488aa799ca",
                  "runId": "5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d",
                  "occurredAt": "2026-08-29T08:29:30Z",
                  "payload": {
                    "seq": 0,
                    "tool": "ask_user",
                    "ok": true,
                    "summary": "你想去哪个城市？"
                  }
                }
                """;
    }
}
