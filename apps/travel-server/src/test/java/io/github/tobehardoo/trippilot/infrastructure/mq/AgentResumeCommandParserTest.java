package io.github.tobehardoo.trippilot.infrastructure.mq;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.EventContractException;
import io.github.tobehardoo.trippilot.support.AgentEventFixtures;
import org.junit.jupiter.api.Test;

class AgentResumeCommandParserTest {

    private final AgentResumeCommandParser parser =
            new AgentResumeCommandParser(new ObjectMapper().findAndRegisterModules());

    @Test
    void parsesAValidResumeCommand() {
        AgentResumeCommand command = parser.parse(validBody().getBytes(StandardCharsets.UTF_8));
        assertThat(command.eventType()).isEqualTo("AGENT_RESUME");
        assertThat(command.schemaVersion()).isEqualTo(1);
        assertThat(command.runId()).hasToString("5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d");
        assertThat(command.payload().answer()).isEqualTo("10月1日出发");
    }

    @Test
    void acceptsTheSharedCrossLanguageFixture() {
        AgentResumeCommand command = parser.parse(
                AgentEventFixtures.load("agent-resume-command-v1", "valid.json").getBytes(StandardCharsets.UTF_8));
        assertThat(command.payload().answer()).isEqualTo("10月1日出发");
    }

    @Test
    void rejectsAnUnsupportedSchemaVersion() {
        String body = validBody().replace("\"schemaVersion\": 1", "\"schemaVersion\": 2");
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsABlankAnswer() {
        String body = validBody().replace("\"answer\": \"10月1日出发\"", "\"answer\": \"   \"");
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsAnOversizedAnswer() {
        String body = validBody().replace("\"answer\": \"10月1日出发\"",
                "\"answer\": \"" + "长".repeat(2001) + "\"");
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
    void rejectsAnUnknownPayloadField() {
        String body = validBody().replace(
                "\"answer\": \"10月1日出发\"",
                "\"answer\": \"10月1日出发\", \"selectedOption\": \"2026-10-01\"");
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    private String validBody() {
        return """
                {
                  "eventType": "AGENT_RESUME",
                  "schemaVersion": 1,
                  "eventId": "8c0d1e2f-3a4b-4c5d-9e6f-0a1b2c3d4e5f",
                  "traceId": "1c2d3e4f-0a1b-4c2d-8e3f-4a5b6c7d8e9f",
                  "tripId": "9ee5e831-90f7-4a60-bb8d-fb488aa799ca",
                  "runId": "5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d",
                  "occurredAt": "2026-08-29T09:00:00Z",
                  "payload": {
                    "answer": "10月1日出发"
                  }
                }
                """;
    }
}
