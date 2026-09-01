package io.github.tobehardoo.trippilot.infrastructure.mq;

import io.github.tobehardoo.trippilot.common.EventContractException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
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
                .isInstanceOf(EventContractException.class);
        assertThatThrownBy(() -> parser.parse(empty.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void parsesProviderFailureV2AndPreservesSafeProviderCode() throws Exception {
        PlanningFailedEvent event = parser.parse(Files.readAllBytes(v2Fixture()));

        assertThat(event.schemaVersion()).isEqualTo(2);
        assertThat(event.payload().errorCategory()).isEqualTo("AUTHENTICATION_ERROR");
        assertThat(event.payload().provider()).isEqualTo("AMAP");
        assertThat(event.payload().operation()).isEqualTo("POI_SEARCH");
        assertThat(event.payload().safeProviderCode()).isEqualTo("10001");
        assertThat(event.payload().displayMessage()).isEqualTo("AMap authentication failed");
    }

    @Test
    void v2AcceptsUnknownFieldsButRejectsMissingRequiredFieldsAndVersions() throws Exception {
        String valid = Files.readString(v2Fixture());
        String unknown = valid.replace(
                "\"safeProviderCode\": \"10001\"",
                "\"safeProviderCode\": \"10001\", \"futureMetadata\": true"
        );
        String missing = valid.replace("\"errorCategory\": \"AUTHENTICATION_ERROR\",", "");
        String unsupported = valid.replace("\"schemaVersion\": 2", "\"schemaVersion\": 3");

        assertThat(parser.parse(unknown.getBytes(StandardCharsets.UTF_8)).schemaVersion())
                .isEqualTo(2);
        assertThatThrownBy(() -> parser.parse(missing.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
        assertThatThrownBy(() -> parser.parse(unsupported.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    @Test
    void v2RejectsCoercedBooleanAndIntegerFields() throws Exception {
        String valid = Files.readString(v2Fixture());
        String stringBoolean = valid.replace("\"retryable\": false", "\"retryable\": \"false\"");
        String decimalRetryCount = valid.replace("\"retryCount\": 0", "\"retryCount\": 0.5");

        assertThatThrownBy(() -> parser.parse(stringBoolean.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
        assertThatThrownBy(() -> parser.parse(decimalRetryCount.getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(EventContractException.class);
    }

    private static Path v2Fixture() {
        Path fromRepository = Path.of(
                "contracts", "fixtures", "planning-failed-event-v2",
                "provider-authentication-failed.json"
        ).toAbsolutePath();
        if (Files.exists(fromRepository)) {
            return fromRepository;
        }
        return Path.of(
                "..", "..", "contracts", "fixtures", "planning-failed-event-v2",
                "provider-authentication-failed.json"
        ).toAbsolutePath();
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
