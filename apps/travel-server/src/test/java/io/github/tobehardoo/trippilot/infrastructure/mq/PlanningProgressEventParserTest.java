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

    @Test
    void parsesV2RepairProgressWithBoundedAttemptStatistics() {
        String body = new String(validBody(), StandardCharsets.UTF_8)
                .replace("\"schemaVersion\":1", "\"schemaVersion\":2")
                .replace("CANDIDATES_RANKING", "REPAIRING")
                .replace("\"candidateCount\":12", "\"attemptIndex\":2,\"actionCount\":3");

        PlanningProgressEvent event = parser.parse(body.getBytes(StandardCharsets.UTF_8));

        assertThat(event.schemaVersion()).isEqualTo(2);
        assertThat(event.payload().stage()).isEqualTo("REPAIRING");
        assertThat(event.payload().statistics())
                .containsEntry("attemptIndex", 2)
                .containsEntry("actionCount", 3);
    }

    @Test
    void rejectsRepairingInV1AndMissingOrOutOfRangeRepairStatistics() {
        String base = new String(validBody(), StandardCharsets.UTF_8)
                .replace("CANDIDATES_RANKING", "REPAIRING");
        String missing = base.replace("\"schemaVersion\":1", "\"schemaVersion\":2");
        String outOfRange = missing.replace(
                "\"candidateCount\":12", "\"attemptIndex\":4,\"actionCount\":1");

        assertThatThrownBy(() -> parser.parse(base.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(PlanningEventContractException.class);
        assertThatThrownBy(() -> parser.parse(missing.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(PlanningEventContractException.class);
        assertThatThrownBy(() -> parser.parse(outOfRange.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(PlanningEventContractException.class);
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
