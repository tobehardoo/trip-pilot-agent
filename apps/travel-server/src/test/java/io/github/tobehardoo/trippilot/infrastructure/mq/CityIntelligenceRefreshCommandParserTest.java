package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.nio.charset.StandardCharsets;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class CityIntelligenceRefreshCommandParserTest {

    private final CityIntelligenceRefreshCommandParser parser =
            new CityIntelligenceRefreshCommandParser(
                    new ObjectMapper().findAndRegisterModules()
            );

    @Test
    void acceptsTheVersionedRefreshCommand() {
        CityIntelligenceRefreshCommand command = parser.parse(json("""
                {
                  "eventType": "CITY_INTELLIGENCE_REFRESH_REQUESTED",
                  "schemaVersion": 1,
                  "eventId": "ca73c2f2-5565-47bd-b660-cbb20225c158",
                  "refreshId": "f8aab348-d72b-498a-8d74-af5a2e0c79ae",
                  "tripId": "9ee5e831-90f7-4a60-bb8d-fb488aa799ca",
                  "occurredAt": "2026-07-26T08:00:00Z",
                  "payload": {
                    "city": "广州",
                    "cityCode": "CN-GD-GZ",
                    "startDate": "2026-08-01",
                    "endDate": "2026-08-04",
                    "sourceIds": ["2d9bc69b-5308-40bd-81c2-e098f12c0d5a"],
                    "requiredCategories": ["OPENING_HOURS"],
                    "idempotencyKey": "21538aaf-fdd9-4b14-9683-dd0e261e063c"
                  }
                }
                """));

        assertThat(command.schemaVersion()).isEqualTo(1);
        assertThat(command.payload().cityCode()).isEqualTo("CN-GD-GZ");
    }

    @Test
    void rejectsUnknownFieldsAndUnsupportedVersions() {
        assertThatThrownBy(() -> parser.parse(json("""
                {
                  "eventType": "CITY_INTELLIGENCE_REFRESH_REQUESTED",
                  "schemaVersion": 2,
                  "eventId": "ca73c2f2-5565-47bd-b660-cbb20225c158",
                  "refreshId": "f8aab348-d72b-498a-8d74-af5a2e0c79ae",
                  "tripId": "9ee5e831-90f7-4a60-bb8d-fb488aa799ca",
                  "occurredAt": "2026-07-26T08:00:00Z",
                  "unexpected": true,
                  "payload": {}
                }
                """))).isInstanceOf(PlanningEventContractException.class);
    }

    private byte[] json(String value) {
        return value.getBytes(StandardCharsets.UTF_8);
    }
}
