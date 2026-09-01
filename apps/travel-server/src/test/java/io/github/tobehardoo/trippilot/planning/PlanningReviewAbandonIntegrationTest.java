package io.github.tobehardoo.trippilot.planning;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.EventRejectedException;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEventParser;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningReviewRequiredEvent;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningReviewRequiredEventParser;
import io.github.tobehardoo.trippilot.support.PlanningCompletedEventFixture;
import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * B12: explicit abandonment of a WAITING_USER review candidate.
 *
 * DELETE /api/planning-tasks/{taskId} keeps its QUEUED/RUNNING/CANCELLING
 * cancel semantics and additionally allows WAITING_USER --abandon-->
 * CANCELLED as a purely local transition: no cancel-command outbox, no
 * itinerary version, no feasibility report, no current-version change.
 */
class PlanningReviewAbandonIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private PlanningReviewRequiredEventParser reviewEventParser;

    @Autowired
    private PlanningCompletedEventParser completedEventParser;

    @Autowired
    private PlanningReviewService reviewService;

    @Autowired
    private PlanningCompletionService completionService;

    private record PlanningContext(
            String accessToken, UUID tripId, UUID taskId, UUID traceId
    ) {
    }

    @Test
    void abandoningAWaitingUserReviewCancelsLocallyAndReleasesTheActiveTaskSlot()
            throws Exception {
        PlanningContext context = contextWithWaitingUser("abandon@example.com");
        UUID currentVersionId = jdbcTemplate.queryForObject(
                "SELECT current_version_id FROM business.itinerary WHERE trip_id = ?",
                UUID.class, context.tripId());
        assertThat(currentVersionId).isNotNull();

        mockMvc.perform(delete("/api/planning-tasks/{taskId}", context.taskId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("CANCELLED"));

        // The abandoned review must be CANCELLED with a single terminal event
        // and no cancel-command outbox: Python already finished that outcome.
        assertThat(taskStatus(context.taskId())).isEqualTo("CANCELLED");
        assertThat(countTerminalEvents(context.taskId(), "PLANNING_CANCELLED")).isEqualTo(1);
        assertThat(jdbcTemplate.queryForObject("""
                SELECT COUNT(*) FROM business.outbox_event
                WHERE aggregate_id = ? AND event_type = 'PLANNING_CANCEL_REQUESTED'
                """, Integer.class, context.taskId())).isZero();

        // The formal itinerary is untouched: same version, same report, and
        // the historical review event/candidate remain for audit.
        assertThat(jdbcTemplate.queryForObject(
                "SELECT current_version_id FROM business.itinerary WHERE trip_id = ?",
                UUID.class, context.tripId())).isEqualTo(currentVersionId);
        assertThat(count("business.itinerary_version")).isEqualTo(1L);
        assertThat(count("business.itinerary_feasibility_report")).isEqualTo(1L);
        assertThat(countTerminalEvents(context.taskId(), "PLANNING_REVIEW_REQUIRED")).isEqualTo(1);

        // The one-active-per-trip slot is released: a new planning task can be
        // queued for the same trip.
        createPlanningTaskRequest(context.accessToken(), context.tripId(), UUID.randomUUID())
                .andExpect(status().isAccepted());

        // Repeating the abandon is idempotent and produces no second terminal
        // event.
        mockMvc.perform(delete("/api/planning-tasks/{taskId}", context.taskId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("CANCELLED"));
        assertThat(countTerminalEvents(context.taskId(), "PLANNING_CANCELLED")).isEqualTo(1);
    }

    @Test
    void abandonIsOwnerScoped() throws Exception {
        PlanningContext owner = contextWithWaitingUser("abandon-owner@example.com");
        String otherAccessToken = registerAndGetAccessToken("abandon-other@example.com");

        mockMvc.perform(delete("/api/planning-tasks/{taskId}", owner.taskId())
                        .header("Authorization", bearer(otherAccessToken)))
                .andExpect(status().isNotFound());

        assertThat(taskStatus(owner.taskId())).isEqualTo("WAITING_USER");
    }

    @Test
    void lateCompletionCannotResurrectAnAbandonedTask() throws Exception {
        PlanningContext context = contextWithWaitingUser("abandon-late-completion@example.com");
        abandon(context);

        PlanningCompletedEvent completed = completedEventParser.parse(
                PlanningCompletedEventFixture.upgradeToV9(
                        PlanningCompletedEventFixture.completedAmapEventV3(
                                UUID.randomUUID(), context.traceId(),
                                context.taskId(), context.tripId()
                        )
                ).getBytes(StandardCharsets.UTF_8));

        assertThatThrownBy(() -> completionService.handle(completed))
                .isInstanceOf(EventRejectedException.class)
                .hasMessageContaining("cannot accept a completion event in status CANCELLED");

        assertThat(taskStatus(context.taskId())).isEqualTo("CANCELLED");
        assertThat(count("business.itinerary_version")).isEqualTo(1L);
    }

    @Test
    void lateReviewCannotResurrectAnAbandonedTask() throws Exception {
        PlanningContext context = contextWithWaitingUser("abandon-late-review@example.com");
        abandon(context);

        assertThatThrownBy(() -> reviewService.handle(reviewEvent(
                context, "review-v1-needs-repair-demo.json")))
                .isInstanceOf(EventRejectedException.class)
                .hasMessageContaining("cannot accept a review event in status CANCELLED");

        assertThat(taskStatus(context.taskId())).isEqualTo("CANCELLED");
        assertThat(count("business.itinerary_version")).isEqualTo(1L);
    }

    // ── helpers ────────────────────────────────────────────────────────────

    private PlanningContext contextWithWaitingUser(String email) throws Exception {
        String accessToken = registerAndGetAccessToken(email);
        UUID tripId = createTrip(accessToken);

        // First task completes a formal v9 itinerary so the trip has a
        // current version that the abandonment must not disturb.
        UUID firstTaskId = createPlanningTask(accessToken, tripId, UUID.randomUUID());
        UUID firstTraceId = jdbcTemplate.queryForObject(
                "SELECT trace_id FROM business.planning_task WHERE id = ?", UUID.class, firstTaskId);
        PlanningCompletedEvent completed = completedEventParser.parse(
                PlanningCompletedEventFixture.upgradeToV9(
                        PlanningCompletedEventFixture.completedAmapEventV3(
                                UUID.randomUUID(), firstTraceId, firstTaskId, tripId
                        )
                ).getBytes(StandardCharsets.UTF_8));
        completionService.handle(completed);

        // Second task lands in WAITING_USER via a review event.
        UUID reviewTaskId = createPlanningTask(accessToken, tripId, UUID.randomUUID());
        UUID reviewTraceId = jdbcTemplate.queryForObject(
                "SELECT trace_id FROM business.planning_task WHERE id = ?",
                UUID.class, reviewTaskId);
        PlanningContext reviewContext = new PlanningContext(
                accessToken, tripId, reviewTaskId, reviewTraceId);
        reviewService.handle(reviewEvent(reviewContext, "review-v1-needs-repair-demo.json"));
        assertThat(taskStatus(reviewTaskId)).isEqualTo("WAITING_USER");
        return reviewContext;
    }

    private void abandon(PlanningContext context) throws Exception {
        mockMvc.perform(delete("/api/planning-tasks/{taskId}", context.taskId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("CANCELLED"));
    }

    private UUID createPlanningTask(String accessToken, UUID tripId, UUID idempotencyKey)
            throws Exception {
        MvcResult result = createPlanningTaskRequest(accessToken, tripId, idempotencyKey)
                .andExpect(status().isAccepted())
                .andReturn();
        return UUID.fromString(json(result).get("taskId").asText());
    }

    private org.springframework.test.web.servlet.ResultActions createPlanningTaskRequest(
            String accessToken, UUID tripId, UUID idempotencyKey) throws Exception {
        return mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", tripId)
                .header("Authorization", bearer(accessToken))
                .header("Idempotency-Key", idempotencyKey));
    }

    private PlanningReviewRequiredEvent reviewEvent(
            PlanningContext context, String fixtureName
    ) throws Exception {
        String fixture = PlanningCompletedEventFixture.sharedReviewV1Fixture(fixtureName);
        JsonNode tree = objectMapper.readTree(fixture);
        ((com.fasterxml.jackson.databind.node.ObjectNode) tree)
                .put("eventId", UUID.randomUUID().toString())
                .put("traceId", context.traceId().toString())
                .put("taskId", context.taskId().toString())
                .put("tripId", context.tripId().toString())
                .put("runId", UUID.randomUUID().toString());
        return reviewEventParser.parse(objectMapper.writeValueAsBytes(tree));
    }

    private String taskStatus(UUID taskId) {
        return jdbcTemplate.queryForObject(
                "SELECT status FROM business.planning_task WHERE id = ?", String.class, taskId);
    }

    private int countTerminalEvents(UUID taskId, String eventType) {
        return jdbcTemplate.queryForObject("""
                SELECT COUNT(*) FROM business.planning_task_event
                WHERE task_id = ? AND event_type = ?
                """, Integer.class, taskId, eventType);
    }

    private long count(String table) {
        Long result = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM " + table, Long.class);
        return result == null ? 0L : result;
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
                                  "endDate": "2026-08-01",
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
