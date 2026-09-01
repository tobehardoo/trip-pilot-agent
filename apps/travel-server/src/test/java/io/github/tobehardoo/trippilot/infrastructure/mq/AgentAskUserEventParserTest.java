package io.github.tobehardoo.trippilot.infrastructure.mq;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.EventContractException;
import io.github.tobehardoo.trippilot.support.AgentEventFixtures;
import org.junit.jupiter.api.Test;

class AgentAskUserEventParserTest {

    private final AgentAskUserEventParser parser = new AgentAskUserEventParser(
            new ObjectMapper().findAndRegisterModules()
    );

    @Test
    void parsesAValidAskUserEvent() {
        AgentAskUserEvent event = parser.parse(validBody().getBytes(StandardCharsets.UTF_8));
        assertThat(event.eventType()).isEqualTo("AGENT_ASK_USER");
        assertThat(event.schemaVersion()).isEqualTo(1);
        assertThat(event.runId()).hasToString("5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d");
        assertThat(event.payload().question()).isEqualTo("行程从哪天开始？");
        assertThat(event.payload().options()).containsExactly("2026-10-01", "2026-10-02");
        assertThat(event.payload().expectedType()).isEqualTo("DATE");
    }

    @Test
    void acceptsTheSharedCrossLanguageFixture() {
        AgentAskUserEvent event = parser.parse(
                AgentEventFixtures.load("agent-ask-user-event-v1", "valid.json").getBytes(StandardCharsets.UTF_8));
        assertThat(event.payload().question()).isEqualTo("行程从哪天开始？");
        assertThat(event.payload().expectedType()).isEqualTo("DATE");
    }

    @Test
    void rejectsAnUnsupportedSchemaVersion() {
        String body = validBody().replace("\"schemaVersion\": 1", "\"schemaVersion\": 2");
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsAnUnknownExpectedType() {
        String body = validBody().replace("\"expectedType\": \"DATE\"", "\"expectedType\": \"EMOJI\"");
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsABlankQuestion() {
        String body = validBody().replace(
                "\"question\": \"行程从哪天开始？\"", "\"question\": \"   \"");
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsMoreThanTenOptions() {
        String body = validBody().replace(
                "\"options\": [\"2026-10-01\", \"2026-10-02\"]", elevenOptions());
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsANonTextualRunId() {
        String body = validBody().replace(
                "\"runId\": \"5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d\"", "\"runId\": 123");
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsAnUnknownEnvelopeField() {
        String body = validBody().replace(
                "\"runId\": \"5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d\",",
                "\"runId\": \"5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d\",\n  \"taskId\": \"5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d\",");
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    private String elevenOptions() {
        StringBuilder options = new StringBuilder("\"options\": [");
        for (int index = 0; index < 11; index++) {
            if (index > 0) {
                options.append(", ");
            }
            options.append("\"选项 ").append(index).append("\"");
        }
        return options.append("]").toString();
    }

    private String validBody() {
        return """
                {
                  "eventType": "AGENT_ASK_USER",
                  "schemaVersion": 1,
                  "eventId": "7b9c0c86-4b5f-4a1f-9f6a-4b6f7d2c9a01",
                  "traceId": "1c2d3e4f-0a1b-4c2d-8e3f-4a5b6c7d8e9f",
                  "tripId": "9ee5e831-90f7-4a60-bb8d-fb488aa799ca",
                  "runId": "5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d",
                  "occurredAt": "2026-08-29T08:30:00Z",
                  "payload": {
                    "question": "行程从哪天开始？",
                    "options": ["2026-10-01", "2026-10-02"],
                    "expectedType": "DATE"
                  }
                }
                """;
    }
}
