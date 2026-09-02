package io.github.tobehardoo.trippilot.infrastructure.mq;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.EventContractException;
import io.github.tobehardoo.trippilot.support.AgentEventFixtures;
import org.junit.jupiter.api.Test;

class AgentCompletedEventParserTest {

    private final AgentCompletedEventParser parser = new AgentCompletedEventParser(
            new ObjectMapper().findAndRegisterModules()
    );

    @Test
    void parsesAValidCompletedEvent() {
        AgentCompletedEvent event = parser.parse(validBody().getBytes(StandardCharsets.UTF_8));
        assertThat(event.eventType()).isEqualTo("AGENT_COMPLETED");
        assertThat(event.schemaVersion()).isEqualTo(1);
        assertThat(event.payload().summary()).isEqualTo("行程已生成：测试行程");
        assertThat(event.payload().slots().path("destination").path("value").asText())
                .isEqualTo("成都");
    }

    @Test
    void acceptsTheSharedCrossLanguageFixture() {
        AgentCompletedEvent event = parser.parse(
                AgentEventFixtures.load("agent-completed-event-v1", "valid.json")
                        .getBytes(StandardCharsets.UTF_8)
        );
        assertThat(event.payload().summary()).isEqualTo("行程已生成：测试行程");
        // P2.8b: the confirmed-slot projection rides the completed event.
        assertThat(event.payload().slots().path("destination").path("value").asText())
                .isEqualTo("成都");
    }

    @Test
    void rejectsAnUnsupportedSchemaVersion() {
        String body = validBody().replace("\"schemaVersion\": 1", "\"schemaVersion\": 2");
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsABlankSummary() {
        String body = validBody().replace(
                "\"summary\": \"行程已生成：测试行程\"", "\"summary\": \"   \""
        );
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsAPayloadThatCarriesAnItinerary() {
        // AUDIT-01（归边 A）：Agent 对话框链不得携带完整 itinerary。
        String body = validBody().replace(
                "\"payload\": {",
                "\"payload\": {\n    \"itinerary\": {\"title\": \"测试行程\"},"
        );
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("AUDIT-01");
    }

    @Test
    void rejectsAnUnknownEnvelopeField() {
        String body = validBody().replace(
                "\"runId\": \"5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d\",",
                "\"runId\": \"5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d\",\n  \"taskId\": \"5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d\","
        );
        assertThatThrownBy(() -> parser.parse(body.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    private String validBody() {
        return """
                {
                  "eventType": "AGENT_COMPLETED",
                  "schemaVersion": 1,
                  "eventId": "be2f3a4b-5c6d-4e7f-9a8b-0c1d2e3f4a5c",
                  "traceId": "1c2d3e4f-0a1b-4c2d-8e3f-4a5b6c7d8e9f",
                  "tripId": "9ee5e831-90f7-4a60-bb8d-fb488aa799ca",
                  "runId": "5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d",
                  "occurredAt": "2026-08-29T08:31:00Z",
                  "payload": {
                    "summary": "行程已生成：测试行程",
                    "slots": {
                      "destination": {"value": "成都", "state": "CONFIRMED"}
                    }
                  }
                }
                """;
    }
}
