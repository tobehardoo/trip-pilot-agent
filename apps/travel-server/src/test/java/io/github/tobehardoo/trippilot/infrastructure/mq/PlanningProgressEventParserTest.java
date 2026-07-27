package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PlanningProgressEventParserTest {

    private final PlanningProgressEventParser parser = new PlanningProgressEventParser(
            new ObjectMapper().findAndRegisterModules()
    );

    @Test
    void parsesAStandardProgressEventWithOptionalStatistics() {
        PlanningProgressEvent event = parser.parse(validBody());

        assertThat(event.eventType()).isEqualTo("PLANNING_PROGRESS");
        assertThat(event.schemaVersion()).isEqualTo(1);
        assertThat(event.payload().stage()).isEqualTo("CANDIDATES_RANKING");
        assertThat(event.payload().sequence()).isEqualTo(5);
        assertThat(event.payload().progress()).isEqualTo(45);
        assertThat(event.payload().statistics()).containsEntry("candidateCount", 12);
    }

    @Test
    void rejectsUnknownStagesAndInvalidSequences() {
        String invalid = new String(validBody(), StandardCharsets.UTF_8)
                .replace("CANDIDATES_RANKING", "UNKNOWN_STAGE")
                .replace("\"sequence\":5", "\"sequence\":0");

        assertThatThrownBy(() -> parser.parse(invalid.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("Invalid PLANNING_PROGRESS event");
    }

    private byte[] validBody() {
        return """
                {
                  "eventType":"PLANNING_PROGRESS",
                  "schemaVersion":1,
                  "eventId":"%s",
                  "traceId":"%s",
                  "taskId":"%s",
                  "tripId":"%s",
                  "occurredAt":"2026-07-27T08:00:00Z",
                  "payload":{
                    "stage":"CANDIDATES_RANKING",
                    "sequence":5,
                    "progress":45,
                    "message":"Ranking candidates against traveler preferences",
                    "statistics":{"candidateCount":12}
                  }
                }
                """.formatted(
                UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()
        ).getBytes(StandardCharsets.UTF_8);
    }
}
