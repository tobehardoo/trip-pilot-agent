package io.github.tobehardoo.trippilot.planning;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * B13_FIX R1 (P0-1): the planning command must carry the authoritative
 * arrivalAt/departureAt in the actual outbox body, and the shared contract
 * fixtures must be readable from Java with the same shape Python uses.
 */
class PlanningOutboxBoundaryContractIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private static final Path CONTRACT_ROOT = Path.of("../../contracts");

    @Test
    void createCommandCarriesAuthoritativeBoundariesInTheOutbox() throws Exception {
        String accessToken = registerAndGetAccessToken("boundary-owner@example.com");
        String tripId = createTripWithBoundaries(accessToken);

        MvcResult result = mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", tripId)
                        .header("Authorization", bearer(accessToken))
                        .header("Idempotency-Key", UUID.randomUUID()))
                .andExpect(status().isAccepted())
                .andReturn();
        UUID taskId = UUID.fromString(json(result).get("taskId").asText());

        String payload = jdbcTemplate.queryForObject(
                "SELECT payload FROM business.outbox_event WHERE aggregate_id = ?",
                String.class, taskId);
        assertThat(payload).isNotNull();
        JsonNode root = objectMapper.readTree(payload);
        JsonNode trip = root.path("payload").path("trip");

        assertThat(root.path("schemaVersion").asInt()).isEqualTo(4);
        assertThat(trip.path("arrivalAt").asText()).isEqualTo("2026-08-01T18:00:00+08:00");
        assertThat(trip.path("departureAt").asText()).isEqualTo("2026-08-03T08:00:00+08:00");
        assertThat(trip.path("startDate").asText()).isEqualTo("2026-08-01");
        assertThat(trip.path("endDate").asText()).isEqualTo("2026-08-03");
        assertThat(trip.path("destination").asText()).isEqualTo("广州");
        assertThat(trip.path("constraints").isObject()).isTrue();
    }

    @Test
    void legacyDateOnlyTripStillPublishesBoundaryFieldsAsNull() throws Exception {
        String accessToken = registerAndGetAccessToken("boundary-legacy@example.com");
        String tripId = createLegacyDateOnlyTrip(accessToken);

        MvcResult result = mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", tripId)
                        .header("Authorization", bearer(accessToken))
                        .header("Idempotency-Key", UUID.randomUUID()))
                .andExpect(status().isAccepted())
                .andReturn();
        UUID taskId = UUID.fromString(json(result).get("taskId").asText());

        String payload = jdbcTemplate.queryForObject(
                "SELECT payload FROM business.outbox_event WHERE aggregate_id = ?",
                String.class, taskId);
        JsonNode root = objectMapper.readTree(payload);
        JsonNode trip = root.path("payload").path("trip");
        assertThat(root.path("schemaVersion").asInt()).isEqualTo(4);
        // Fields present, null for legacy trips — never absent.
        assertThat(trip.has("arrivalAt")).isTrue();
        assertThat(trip.path("arrivalAt").isNull()).isTrue();
        assertThat(trip.has("departureAt")).isTrue();
        assertThat(trip.path("departureAt").isNull()).isTrue();
    }

    @Test
    void sharedCreateV4FixtureIsReadableFromJavaWithThePythonShape() throws Exception {
        String fixture = Files.readString(
                CONTRACT_ROOT.resolve("fixtures/planning-create-command-v4/valid.json"));
        JsonNode root = objectMapper.readTree(fixture);
        assertThat(root.path("schemaVersion").asInt()).isEqualTo(4);
        JsonNode trip = root.path("payload").path("trip");
        assertThat(trip.has("arrivalAt")).isTrue();
        assertThat(trip.has("departureAt")).isTrue();
        assertThat(trip.has("startDate")).isTrue();
        assertThat(trip.has("constraints")).isTrue();
    }

    @Test
    void outboxBodyNeverCarriesSelectionTokens() throws Exception {
        // B13_FIX R5 (P1-2): selection tokens are request-only.  They must
        // never reach the outbox command — the Python PlaceRef forbids
        // unknown fields, so a leaked token would dead-letter the plan.
        String accessToken = registerAndGetAccessToken("token-leak@example.com");
        String tripId = createLegacyDateOnlyTrip(accessToken);

        MvcResult result = mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", tripId)
                        .header("Authorization", bearer(accessToken))
                        .header("Idempotency-Key", UUID.randomUUID()))
                .andExpect(status().isAccepted())
                .andReturn();
        UUID taskId = UUID.fromString(json(result).get("taskId").asText());

        String payload = jdbcTemplate.queryForObject(
                "SELECT payload FROM business.outbox_event WHERE aggregate_id = ?",
                String.class, taskId);
        assertThat(payload).isNotNull();
        assertThat(payload).doesNotContain("selectionToken");
    }

    private String registerAndGetAccessToken(String email) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "email": "%s",
                                  "password": "StrongPass123!",
                                  "displayName": "Traveler"
                                }
                                """.formatted(email)))
                .andExpect(status().isCreated())
                .andReturn();
        return json(result).get("accessToken").asText();
    }

    private JsonNode json(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsByteArray());
    }

    private String bearer(String accessToken) {
        return "Bearer " + accessToken;
    }

    private String createTripWithBoundaries(String accessToken) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "边界权威",
                                  "destination": "广州",
                                  "arrivalAt": "2026-08-01T18:00:00+08:00",
                                  "departureAt": "2026-08-03T08:00:00+08:00",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mealWindows": [],
                                    "mobilityLevel": "STANDARD"
                                  }
                                }
                                """))
                .andExpect(status().isCreated())
                .andReturn();
        return json(result).get("id").asText();
    }

    private String createLegacyDateOnlyTrip(String accessToken) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "旧日期行程",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-03",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mealWindows": [],
                                    "mobilityLevel": "STANDARD"
                                  }
                                }
                                """))
                .andExpect(status().isCreated())
                .andReturn();
        return json(result).get("id").asText();
    }
}
