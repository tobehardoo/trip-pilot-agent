package io.github.tobehardoo.trippilot.messaging;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

public class PlanningFailedEventParserTest {

    private final PlanningFailedEventParser parser =
            new PlanningFailedEventParser(new ObjectMapper().findAndRegisterModules());

    @Test
    void parsesAnActionableInfeasibilityEvent() {
        UUID eventId = UUID.randomUUID();
        PlanningFailedEvent event = parser.parse(json(eventId).getBytes(StandardCharsets.UTF_8));

        assertThat(event.eventId()).isEqualTo(eventId);
        assertThat(event.payload().errorCode()).isEqualTo("NO_FEASIBLE_ITINERARY");
        assertThat(event.payload().conflicts()).singleElement()
                .extracting(PlanningFailedEvent.Conflict::code)
                .isEqualTo("INSUFFICIENT_DAY_CAPACITY");
        assertThat(event.payload().relaxationSuggestions()).singleElement()
                .extracting(PlanningFailedEvent.Relaxation::code)
                .isEqualTo("REDUCE_OPTIONAL_ACTIVITIES");
    }

    @Test
    void rejectsUnknownFieldsAndEmptyConflicts() {
        String unknown = json(UUID.randomUUID()).replace(
                "\"status\": \"FAILED\"", "\"status\": \"FAILED\", \"secret\": true");
        String empty = json(UUID.randomUUID()).replace(
                "\"conflicts\": [{", "\"conflicts\": [], \"ignored\": [{");

        assertThatThrownBy(() -> parser.parse(unknown.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(PlanningEventContractException.class);
        assertThatThrownBy(() -> parser.parse(empty.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(PlanningEventContractException.class);
    }

    public static String json(UUID eventId) {
        return """
                {
                  "eventType": "PLANNING_FAILED",
                  "schemaVersion": 1,
                  "eventId": "%s",
                  "traceId": "8f5ef9c2-c194-4292-b847-5b9dcfda978b",
                  "taskId": "b0642d34-e24f-4b24-9ea7-82a68a4be781",
                  "tripId": "08be9aca-fb30-4309-aa4b-93c240f19d75",
                  "runId": "d5be64f7-d498-58fc-a9de-a27337df9509",
                  "occurredAt": "2026-07-23T03:00:00Z",
                  "payload": {
                    "status": "FAILED",
                    "errorCode": "NO_FEASIBLE_ITINERARY",
                    "message": "活动、交通与固定安排无法同时放入可用时间",
                    "conflicts": [{
                      "code": "INSUFFICIENT_DAY_CAPACITY",
                      "message": "当日容量不足",
                      "affected": ["不可移动安排"]
                    }],
                    "relaxationSuggestions": [{
                      "code": "REDUCE_OPTIONAL_ACTIVITIES",
                      "message": "减少一个可选活动"
                    }]
                  }
                }
                """.formatted(eventId);
    }
}
