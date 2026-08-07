package io.github.tobehardoo.trippilot.trip;

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

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * B2: unified {@code PUT /api/trips/{id}/configuration}.
 *
 * Trip metadata and constraints are updated atomically under one optimistic
 * lock; the current itinerary becomes stale until a replan completes against
 * the new version. Saving configuration never rewrites itinerary-version
 * snapshots.
 */
class TripConfigurationIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void updatesTripMetadataAndConstraintsAtomically() throws Exception {
        String accessToken = registerAndGetAccessToken("config@example.com");
        String tripId = json(createTrip(accessToken).andReturn()).get("id").asText();

        mockMvc.perform(put("/api/trips/{tripId}/configuration", tripId)
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "version": 0,
                                  "title": "深圳周末慢游",
                                  "destination": "深圳",
                                  "startDate": "2026-09-15",
                                  "endDate": "2026-09-17",
                                  "constraints": {
                                    "budgetAmount": 5000,
                                    "travelers": 2,
                                    "travelerType": "COUPLE",
                                    "pace": "RELAXED",
                                    "preferences": ["美食"],
                                    "fixedSchedules": [],
                                    "mustVisitPlaces": ["世界之窗"],
                                    "mealWindows": [{
                                      "mealType": "LUNCH",
                                      "startTime": "12:30",
                                      "endTime": "13:30"
                                    }]
                                  }
                                }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("深圳周末慢游"))
                .andExpect(jsonPath("$.destination").value("深圳"))
                .andExpect(jsonPath("$.startDate").value("2026-09-15"))
                .andExpect(jsonPath("$.endDate").value("2026-09-17"))
                .andExpect(jsonPath("$.version").value(1))
                .andExpect(jsonPath("$.constraints.budgetAmount").value(5000))
                .andExpect(jsonPath("$.constraints.mustVisitPlaces[0]").value("世界之窗"))
                .andExpect(jsonPath("$.constraints.mealWindows[0].source").value("USER_SET"));

        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("深圳周末慢游"))
                .andExpect(jsonPath("$.version").value(1));
    }

    @Test
    void rejectsConfigurationWithStaleVersion() throws Exception {
        String accessToken = registerAndGetAccessToken("config-version@example.com");
        String tripId = json(createTrip(accessToken).andReturn()).get("id").asText();

        mockMvc.perform(put("/api/trips/{tripId}/configuration", tripId)
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(configBody("7", "深圳周末慢游", "深圳", "2026-09-15", "2026-09-17")))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("TRIP_VERSION_CONFLICT"));

        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("广州四日慢游"))
                .andExpect(jsonPath("$.version").value(0));
    }

    @Test
    void doesNotPartiallyApplyConfigurationOnInvalidDates() throws Exception {
        String accessToken = registerAndGetAccessToken("config-atomic@example.com");
        String tripId = json(createTrip(accessToken).andReturn()).get("id").asText();

        mockMvc.perform(put("/api/trips/{tripId}/configuration", tripId)
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(configBody("0", "深圳周末慢游", "深圳", "2026-09-17", "2026-09-15")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));

        // Neither metadata nor version nor constraints changed.
        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("广州四日慢游"))
                .andExpect(jsonPath("$.destination").value("广州"))
                .andExpect(jsonPath("$.startDate").value("2026-09-01"))
                .andExpect(jsonPath("$.endDate").value("2026-09-04"))
                .andExpect(jsonPath("$.version").value(0))
                .andExpect(jsonPath("$.constraints.budgetAmount").value(6000));
    }

    @Test
    void configurationSaveLeavesItinerarySnapshotUntouched() throws Exception {
        String accessToken = registerAndGetAccessToken("config-snapshot@example.com");
        String tripId = json(createTrip(accessToken).andReturn()).get("id").asText();
        UUID planningTaskId = insertPlanningTask(UUID.fromString(tripId), "CREATE", 0, null);
        UUID versionId = insertItineraryWithVersion(
                UUID.fromString(tripId), planningTaskId, 1, "{\"old\": true}");

        mockMvc.perform(put("/api/trips/{tripId}/configuration", tripId)
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(configBody("0", "深圳周末慢游", "深圳", "2026-09-15", "2026-09-17")))
                .andExpect(status().isOk());

        String snapshot = jdbcTemplate.queryForObject(
                "SELECT constraint_snapshot::text FROM business.itinerary_version WHERE id = ?::uuid",
                String.class, versionId);
        org.assertj.core.api.Assertions.assertThat(snapshot).isEqualTo("{\"old\": true}");

        // The live constraint row carries the new configuration.
        String live = jdbcTemplate.queryForObject(
                "SELECT meal_windows::text FROM business.trip_constraint WHERE trip_id = ?::uuid",
                String.class, tripId);
        org.assertj.core.api.Assertions.assertThat(live).contains("DINNER");
    }

    @Test
    void staleFlagTracksConstraintFreshnessAcrossReplan() throws Exception {
        String accessToken = registerAndGetAccessToken("config-stale@example.com");
        String tripId = json(createTrip(accessToken).andReturn()).get("id").asText();

        // Fresh: planned at trip version 0.
        UUID firstTask = insertPlanningTask(UUID.fromString(tripId), "CREATE", 0, null);
        UUID firstVersionId = insertItineraryWithVersion(UUID.fromString(tripId), firstTask, 1, "{}");
        mockMvc.perform(get("/api/trips/{tripId}/itinerary", tripId)
                        .header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.stale").value(false));

        // Configuration save bumps the trip version; itinerary is now stale.
        mockMvc.perform(put("/api/trips/{tripId}/configuration", tripId)
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(configBody("0", "深圳周末慢游", "深圳", "2026-09-15", "2026-09-17")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.version").value(1));
        mockMvc.perform(get("/api/trips/{tripId}/itinerary", tripId)
                        .header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.stale").value(true));

        // Replan against version 1 creates a fresh current version.
        UUID replanTask = insertPlanningTask(UUID.fromString(tripId), "REPLAN", 1, firstVersionId);
        insertItineraryWithVersion(UUID.fromString(tripId), replanTask, 2, "{}");
        mockMvc.perform(get("/api/trips/{tripId}/itinerary", tripId)
                        .header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.stale").value(false));

        // Another configuration save makes it stale again.
        mockMvc.perform(put("/api/trips/{tripId}/configuration", tripId)
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(configBody("1", "深圳三日", "深圳", "2026-09-16", "2026-09-18")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.version").value(2));
        mockMvc.perform(get("/api/trips/{tripId}/itinerary", tripId)
                        .header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.stale").value(true));
    }

    private String configBody(
            String version, String title, String destination, String startDate, String endDate) {
        return """
                {
                  "version": %s,
                  "title": "%s",
                  "destination": "%s",
                  "startDate": "%s",
                  "endDate": "%s",
                  "constraints": {
                    "budgetAmount": 5000,
                    "travelers": 2,
                    "travelerType": "COUPLE",
                    "pace": "RELAXED",
                    "preferences": ["美食"],
                    "fixedSchedules": []
                  }
                }
                """.formatted(version, title, destination, startDate, endDate);
    }

    private UUID insertPlanningTask(
            UUID tripId, String taskType, int baselineVersion, UUID baseItineraryVersionId) {
        UUID taskId = UUID.randomUUID();
        if ("REPLAN".equals(taskType)) {
            jdbcTemplate.update("""
                    INSERT INTO business.planning_task(
                        id, trip_id, idempotency_key, task_type, status,
                        baseline_trip_version, baseline_itinerary_version_id, impacted_dates,
                        constraint_snapshot, guide_evidence_snapshot, trace_id, version
                    ) VALUES (
                        ?::uuid, ?::uuid, ?::uuid, 'REPLAN', 'SUCCEEDED',
                        ?, ?::uuid, '["2026-09-15"]'::jsonb,
                        '{}'::jsonb, '{"facts":[]}'::jsonb, ?::uuid, 0
                    )
                    """, taskId, tripId, UUID.randomUUID(), baselineVersion,
                    baseItineraryVersionId, UUID.randomUUID());
        } else {
            jdbcTemplate.update("""
                    INSERT INTO business.planning_task(
                        id, trip_id, idempotency_key, task_type, status,
                        baseline_trip_version, constraint_snapshot, guide_evidence_snapshot,
                        trace_id, version
                    ) VALUES (
                        ?::uuid, ?::uuid, ?::uuid, 'CREATE', 'SUCCEEDED',
                        ?, '{}'::jsonb, '{"facts":[]}'::jsonb, ?::uuid, 0
                    )
                    """, taskId, tripId, UUID.randomUUID(), baselineVersion,
                    UUID.randomUUID());
        }
        return taskId;
    }

    private UUID insertItineraryWithVersion(UUID tripId, UUID planningTaskId, int versionNumber, String snapshot) {
        UUID versionId = UUID.randomUUID();
        // A trip has at most one itinerary row; a replan adds a version to the
        // same itinerary and re-points its current version.
        java.util.List<UUID> existing = jdbcTemplate.queryForList(
                "SELECT id FROM business.itinerary WHERE trip_id = ?::uuid",
                UUID.class, tripId);
        UUID itineraryId = existing.isEmpty() ? UUID.randomUUID() : existing.get(0);
        // The itinerary and its current version reference each other, so create
        // the itinerary with a null current version, then the version, then wire
        // them together.
        if (existing.isEmpty()) {
            jdbcTemplate.update("""
                    INSERT INTO business.itinerary(id, trip_id, current_version_id)
                    VALUES (?::uuid, ?::uuid, NULL)
                    """, itineraryId, tripId);
        }
        jdbcTemplate.update("""
                INSERT INTO business.itinerary_version(
                    id, itinerary_id, version_number, planning_task_id, title,
                    estimated_total_cost, provider, constraint_snapshot
                ) VALUES (
                    ?::uuid, ?::uuid, ?, ?::uuid, '测试行程', 100.00, 'DEMO', ?::jsonb
                )
                """, versionId, itineraryId, versionNumber, planningTaskId, snapshot);
        jdbcTemplate.update("""
                UPDATE business.itinerary
                SET current_version_id = ?::uuid
                WHERE id = ?::uuid
                """, versionId, itineraryId);
        return versionId;
    }

    private UUID ownerIdFor(String email) {
        return jdbcTemplate.queryForObject(
                "SELECT id FROM business.user_account WHERE email = ?",
                UUID.class, email);
    }

    private org.springframework.test.web.servlet.ResultActions createTrip(String accessToken) throws Exception {
        return mockMvc.perform(post("/api/trips")
                .header("Authorization", bearer(accessToken))
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                        {
                          "title": "广州四日慢游",
                          "destination": "广州",
                          "startDate": "2026-09-01",
                          "endDate": "2026-09-04",
                          "constraints": {
                            "budgetAmount": 6000,
                            "travelers": 2,
                            "travelerType": "FRIENDS",
                            "pace": "BALANCED",
                            "preferences": ["美食", "历史"],
                            "fixedSchedules": []
                          }
                        }
                        """));
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
}
