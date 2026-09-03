package io.github.tobehardoo.trippilot.planning;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;

/**
 * Stale-task reaper (P3): an active planning task whose state has not moved
 * for the configured timeout must be failed through the regular failure path
 * — terminal event recorded, trip phase rolled back, and the
 * one-active-task-per-trip lock released.  Freshly active tasks are never
 * touched.
 */
class PlanningStaleTaskSweeperIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private PlanningStaleTaskSweeperJob sweeper;

    @Test
    void reapsAStaleRunningTaskAndReleasesTheTripPlanningLock() throws Exception {
        String accessToken = registerAndGetAccessToken("stale-reaper@example.com");
        UUID tripId = createTrip(accessToken);
        UUID taskId = UUID.fromString(json(createPlanningTask(accessToken, tripId))
                .get("taskId").asText());
        // Age the task past the 30-minute default timeout while RUNNING.
        jdbcTemplate.update("""
                UPDATE business.planning_task
                SET status = 'RUNNING',
                    updated_at = now() - INTERVAL '31 minutes'
                WHERE id = ?
                """, taskId);

        sweeper.reapStaleTasks();

        assertThat(jdbcTemplate.queryForObject(
                "SELECT status FROM business.planning_task WHERE id = ?",
                String.class, taskId)).isEqualTo("FAILED");
        assertThat(jdbcTemplate.queryForObject(
                "SELECT error_code FROM business.planning_task WHERE id = ?",
                String.class, taskId)).isEqualTo("STALE_TASK_REAPED");
        Integer failureEvents = jdbcTemplate.queryForObject("""
                SELECT count(*) FROM business.planning_task_event
                WHERE task_id = ? AND event_type = 'PLANNING_FAILED'
                """, Integer.class, taskId);
        assertThat(failureEvents).isEqualTo(1);
        // First-attempt trip rolls back to DRAFT so the workspace exits the
        // planning view.
        assertThat(jdbcTemplate.queryForObject(
                "SELECT status FROM business.trip WHERE id = ?",
                String.class, tripId)).isEqualTo("DRAFT");

        // The one-active-task-per-trip lock is released: a fresh task can be
        // created for the same trip.
        createPlanningTask(accessToken, tripId);
        Integer activeTasks = jdbcTemplate.queryForObject("""
                SELECT count(*) FROM business.planning_task
                WHERE trip_id = ? AND status IN
                      ('CREATED', 'QUEUED', 'RUNNING', 'WAITING_USER', 'RETRYING', 'CANCELLING')
                """, Integer.class, tripId);
        assertThat(activeTasks).isEqualTo(1);
    }

    @Test
    void leavesFreshlyActiveTasksAlone() throws Exception {
        String accessToken = registerAndGetAccessToken("stale-reaper-fresh@example.com");
        UUID tripId = createTrip(accessToken);
        UUID taskId = UUID.fromString(json(createPlanningTask(accessToken, tripId))
                .get("taskId").asText());
        jdbcTemplate.update(
                "UPDATE business.planning_task SET status = 'RUNNING' WHERE id = ?",
                taskId);

        sweeper.reapStaleTasks();

        assertThat(jdbcTemplate.queryForObject(
                "SELECT status FROM business.planning_task WHERE id = ?",
                String.class, taskId)).isEqualTo("RUNNING");
        Integer failureEvents = jdbcTemplate.queryForObject("""
                SELECT count(*) FROM business.planning_task_event
                WHERE task_id = ? AND event_type = 'PLANNING_FAILED'
                """, Integer.class, taskId);
        assertThat(failureEvents).isZero();
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

    private UUID createTrip(String accessToken) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "广州一日游",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 1000,
                                    "travelers": 2,
                                    "travelerType": "FRIENDS",
                                    "pace": "BALANCED",
                                    "preferences": ["美食"],
                                    "fixedSchedules": []
                                  }
                                }
                                """))
                .andExpect(status().isCreated())
                .andReturn();
        return UUID.fromString(json(result).get("id").asText());
    }

    private MvcResult createPlanningTask(String accessToken, UUID tripId) throws Exception {
        return mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", tripId)
                        .header("Authorization", bearer(accessToken))
                        .header("Idempotency-Key", UUID.randomUUID().toString()))
                .andExpect(status().isAccepted())
                .andReturn();
    }

    private JsonNode json(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsString());
    }

    private String bearer(String token) {
        return "Bearer " + token;
    }
}
