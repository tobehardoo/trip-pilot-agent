package io.github.tobehardoo.trippilot.planning;

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
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class InternalPlanningDiagnosticsIntegrationTest extends PostgresIntegrationTest {

    private static final String INTERNAL_TOKEN = "local-development-only";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void exposesFailedTaskStagesOnlyToInternalCallersAndRetriesIdempotently() throws Exception {
        String ownerToken = registerAndGetAccessToken("diagnostic-owner@example.com");
        UUID tripId = createTrip(ownerToken);
        MvcResult createTask = mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", tripId)
                        .header("Authorization", bearer(ownerToken))
                        .header("Idempotency-Key", UUID.randomUUID()))
                .andExpect(status().isAccepted())
                .andReturn();
        UUID taskId = UUID.fromString(json(createTask).get("taskId").asText());
        jdbcTemplate.update("""
                UPDATE business.planning_task
                SET status = 'FAILED', error_code = 'PROVIDER_TIMEOUT',
                    error_message = 'Provider timed out', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """, taskId);
        jdbcTemplate.update("""
                INSERT INTO business.planning_task_event(event_id, task_id, event_type, schema_version, payload)
                VALUES (?, ?, 'PLANNING_PROGRESS', 1, '{"stage":"ROUTES_CALCULATING"}'::jsonb)
                """, UUID.randomUUID(), taskId);

        mockMvc.perform(get("/api/internal/diagnostics/planning-failures"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value("INTERNAL_ACCESS_DENIED"));
        mockMvc.perform(get("/api/internal/diagnostics/planning-failures")
                        .header("X-Internal-Token", INTERNAL_TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[0].taskId").value(taskId.toString()))
                .andExpect(jsonPath("$.items[0].lastStage").value("ROUTES_CALCULATING"))
                .andExpect(jsonPath("$.items[0].errorCode").value("PROVIDER_TIMEOUT"))
                .andExpect(jsonPath("$.items[0].ownerId").doesNotExist());

        UUID retryKey = UUID.randomUUID();
        MvcResult firstRetry = mockMvc.perform(post(
                                "/api/internal/diagnostics/planning-tasks/{taskId}/retries", taskId
                        )
                        .header("X-Internal-Token", INTERNAL_TOKEN)
                        .header("Idempotency-Key", retryKey))
                .andExpect(status().isAccepted())
                .andReturn();
        MvcResult secondRetry = mockMvc.perform(post(
                                "/api/internal/diagnostics/planning-tasks/{taskId}/retries", taskId
                        )
                        .header("X-Internal-Token", INTERNAL_TOKEN)
                        .header("Idempotency-Key", retryKey))
                .andExpect(status().isAccepted())
                .andReturn();
        assertThat(json(firstRetry).get("taskId").asText())
                .isEqualTo(json(secondRetry).get("taskId").asText())
                .isNotEqualTo(taskId.toString());
    }

    private UUID createTrip(String token) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title":"Diagnostics trip", "destination":"Guangzhou",
                                  "startDate":"2026-08-01", "endDate":"2026-08-02",
                                  "constraints":{"budgetAmount":1000,"travelers":1,
                                  "travelerType":"SOLO","pace":"BALANCED",
                                  "preferences":[],"fixedSchedules":[]}
                                }
                                """))
                .andExpect(status().isCreated())
                .andReturn();
        return UUID.fromString(json(result).get("id").asText());
    }

    private String registerAndGetAccessToken(String email) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"%s","password":"StrongPass123!","displayName":"Traveler"}
                                """.formatted(email)))
                .andExpect(status().isCreated())
                .andReturn();
        return json(result).get("accessToken").asText();
    }

    private JsonNode json(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsByteArray());
    }

    private String bearer(String token) {
        return "Bearer " + token;
    }

    private org.assertj.core.api.AbstractStringAssert<?> assertThat(String value) {
        return org.assertj.core.api.Assertions.assertThat(value);
    }
}
