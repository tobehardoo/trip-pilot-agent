package io.github.tobehardoo.trippilot.planning;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * B6J.2.1 F3: Task API eventType-aware six-state read model.
 *
 * The API must derive its outcome from task.status AND the latest outcome
 * eventType together: SUCCEEDED exposes a VERIFIED report and evaluation
 * (no candidate), WAITING_USER exposes an UNVERIFIED/NEEDS_REPAIR report and
 * a fingerprint-consistent candidate (no evaluation), and QUEUED/RUNNING/
 * FAILED/CANCELLED expose none of the three.  Any contradictory payload
 * combination must fail closed instead of being passed through.
 */
class PlanningTaskReadModelIntegrationTest extends PostgresIntegrationTest {

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

    @Autowired
    private PlanningTaskService planningTaskService;

    private record PlanningContext(
            String accessToken, UUID tripId, UUID taskId, UUID traceId
    ) {
    }

    // ── SUCCEEDED truth table ─────────────────────────────────────────────

    @Test
    void succeededExposesVerifiedReportAndEvaluationWithoutCandidate() throws Exception {
        PlanningContext context = createPlanningContext("readmodel-succeeded@example.com");
        completionService.handle(completedEvent(context));

        JsonNode task = getTask(context);

        assertThat(task.path("status").asText()).isEqualTo("SUCCEEDED");
        assertThat(task.path("feasibilityReport").path("status").asText())
                .isEqualTo("VERIFIED");
        assertThat(task.path("evaluation").isMissingNode()).isFalse();
        assertThat(task.path("evaluation").isNull()).isFalse();
        assertThat(task.path("candidateItinerary").isMissingNode()
                || task.path("candidateItinerary").isNull()).isTrue();
    }

    // ── WAITING_USER truth table ──────────────────────────────────────────

    @Test
    void waitingUserExposesReportAndCandidateWithoutEvaluation() throws Exception {
        PlanningContext context = createPlanningContext("readmodel-waiting@example.com");
        reviewService.handle(reviewEvent(context, "review-v1-needs-repair-demo.json"));

        JsonNode task = getTask(context);

        assertThat(task.path("status").asText()).isEqualTo("WAITING_USER");
        assertThat(task.path("feasibilityReport").path("status").asText())
                .isEqualTo("NEEDS_REPAIR");
        assertThat(task.path("candidateItinerary").path("title").asText())
                .isEqualTo("Benchmark itinerary");
        assertThat(task.path("candidateItinerary").path("days")).hasSize(1);
        assertThat(task.path("evaluation").isMissingNode()
                || task.path("evaluation").isNull()).isTrue();
    }

    // ── QUEUED / RUNNING ──────────────────────────────────────────────────

    @Test
    void queuedExposesNoOutcomeFields() throws Exception {
        PlanningContext context = createPlanningContext("readmodel-queued@example.com");
        JsonNode task = getTask(context);
        assertThat(task.path("status").asText()).isEqualTo("QUEUED");
        assertNoOutcomeFields(task);
    }

    @Test
    void runningExposesNoOutcomeFields() throws Exception {
        PlanningContext context = createPlanningContext("readmodel-running@example.com");
        setTaskState(context, "RUNNING", "PLANNING_PROGRESS", """
                {"status":"RUNNING","stage":"constraints","sequence":1}
                """);
        JsonNode task = getTask(context);
        assertThat(task.path("status").asText()).isEqualTo("RUNNING");
        assertNoOutcomeFields(task);
    }

    // ── FAILED / CANCELLED ────────────────────────────────────────────────

    @Test
    void failedExposesNoOutcomeFieldsButKeepsErrorFields() throws Exception {
        PlanningContext context = createPlanningContext("readmodel-failed@example.com");
        setTaskState(context, "FAILED", "PLANNING_FAILED", """
                {"status":"FAILED","errorCode":"STALE_TRIP_VERSION","message":"boom"}
                """);
        JsonNode task = getTask(context);
        assertThat(task.path("status").asText()).isEqualTo("FAILED");
        assertThat(task.path("errorCode").asText()).isEqualTo("STALE_TRIP_VERSION");
        assertNoOutcomeFields(task);
    }

    @Test
    void failedRestSnapshotExposesConflictsAndRelaxationSuggestions() throws Exception {
        PlanningContext context = createPlanningContext("readmodel-failed-rest@example.com");
        setTaskState(context, "FAILED", "PLANNING_FAILED", """
                {"status":"FAILED","errorCode":"NO_FEASIBLE_ITINERARY",
                 "errorCategory":"PLANNING_INFEASIBLE","provider":"AMAP",
                 "operation":"PLANNING","retryable":false,"retryCount":0,
                 "fallbackAttempted":false,"fallbackSucceeded":false,
                 "safeMessage":"时间不足，请调整条件后重试",
                 "requestedProviderMode":"REAL_ONLY","primaryProvider":"AMAP",
                 "actualProviders":["AMAP"],
                 "conflicts":[{"code":"INSUFFICIENT_DAY_CAPACITY",
                     "message":"实际交通时长无法在固定返程时间前完成",
                     "affected":["DEPARTURE"]}],
                 "relaxationSuggestions":[{"code":"EXTEND_AVAILABLE_TIME",
                     "message":"请提前出发、延后返程时间，或减少前序行程"}]}
                """);
        JsonNode task = getTask(context);
        assertThat(task.path("status").asText()).isEqualTo("FAILED");
        assertThat(task.path("safeMessage").asText()).isEqualTo("时间不足，请调整条件后重试");
        assertThat(task.path("conflicts")).hasSize(1);
        assertThat(task.path("conflicts").path(0).path("code").asText())
                .isEqualTo("INSUFFICIENT_DAY_CAPACITY");
        assertThat(task.path("conflicts").path(0).path("message").asText())
                .contains("固定返程时间");
        assertThat(task.path("conflicts").path(0).path("affected").path(0).asText())
                .isEqualTo("DEPARTURE");
        assertThat(task.path("relaxationSuggestions")).hasSize(1);
        assertThat(task.path("relaxationSuggestions").path(0).path("code").asText())
                .isEqualTo("EXTEND_AVAILABLE_TIME");
        assertThat(task.path("relaxationSuggestions").path(0).path("message").asText())
                .contains("提前出发");
    }

    @Test
    void cancelledExposesNoOutcomeFields() throws Exception {
        PlanningContext context = createPlanningContext("readmodel-cancelled@example.com");
        setTaskState(context, "CANCELLED", "PLANNING_CANCELLED", """
                {"status":"CANCELLED"}
                """);
        JsonNode task = getTask(context);
        assertThat(task.path("status").asText()).isEqualTo("CANCELLED");
        assertNoOutcomeFields(task);
    }

    // ── B6J.2.1 F3 negative cases: contradictory payloads fail closed ─────

    @Test
    void waitingUserPayloadWithEvaluationFailsClosed() throws Exception {
        assertOutcomeInvalid("WAITING_USER", "PLANNING_REVIEW_REQUIRED", """
                {"status":"WAITING_USER",
                 "candidateItinerary":{"title":"Benchmark itinerary","days":[]},
                 "feasibilityReport":{"status":"NEEDS_REPAIR","schemaVersion":1},
                 "evaluation":{"score":98}}
                """);
    }

    @Test
    void waitingUserPayloadWithVerifiedReportFailsClosed() throws Exception {
        assertOutcomeInvalid("WAITING_USER", "PLANNING_REVIEW_REQUIRED", """
                {"status":"WAITING_USER",
                 "candidateItinerary":{"title":"Benchmark itinerary","days":[]},
                 "feasibilityReport":{"status":"VERIFIED","schemaVersion":1}}
                """);
    }

    @Test
    void waitingUserPayloadMissingCandidateFailsClosed() throws Exception {
        assertOutcomeInvalid("WAITING_USER", "PLANNING_REVIEW_REQUIRED", """
                {"status":"WAITING_USER",
                 "feasibilityReport":{"status":"NEEDS_REPAIR","schemaVersion":1}}
                """);
    }

    @Test
    void waitingUserPayloadWithMalformedCandidateFailsClosed() throws Exception {
        assertOutcomeInvalid("WAITING_USER", "PLANNING_REVIEW_REQUIRED", """
                {"status":"WAITING_USER",
                 "candidateItinerary":{"not":"an itinerary"},
                 "feasibilityReport":{"status":"NEEDS_REPAIR","schemaVersion":1}}
                """);
    }

    @Test
    void waitingUserPayloadWithMalformedFingerprintFailsClosed() throws Exception {
        // The fingerprint is bound to the wire itinerary by the parser before
        // persistence; the stored candidate is a typed-DTO re-serialisation
        // that is not byte-identical to the wire tree (costSource defaulting,
        // BigDecimal normalisation), so recomputation is impossible.  The
        // read model must still reject a malformed fingerprint format.
        assertOutcomeInvalid("WAITING_USER", "PLANNING_REVIEW_REQUIRED", """
                {"status":"WAITING_USER",
                 "candidateItinerary":{"title":"Benchmark itinerary","days":[
                    {"date":"2026-08-01","activities":[
                       {"title":"a","startTime":"2026-08-01T09:00:00+08:00","endTime":"2026-08-01T10:00:00+08:00"}]}]},
                 "feasibilityReport":{"status":"NEEDS_REPAIR","schemaVersion":1,
                     "itineraryFingerprint":"not-a-64-hex-fingerprint"}}
                """);
    }

    @Test
    void succeededPayloadWithCandidateFailsClosed() throws Exception {
        assertOutcomeInvalid("SUCCEEDED", "PLANNING_COMPLETED", """
                {"status":"SUCCEEDED",
                 "candidateItinerary":{"title":"Benchmark itinerary","days":[]},
                 "feasibilityReport":{"status":"VERIFIED","schemaVersion":1},
                 "evaluation":{"score":90}}
                """);
    }

    @Test
    void succeededPayloadWithNeedsRepairReportFailsClosed() throws Exception {
        assertOutcomeInvalid("SUCCEEDED", "PLANNING_COMPLETED", """
                {"status":"SUCCEEDED",
                 "feasibilityReport":{"status":"NEEDS_REPAIR","schemaVersion":1},
                 "evaluation":{"score":90}}
                """);
    }

    @Test
    void succeededPayloadMissingEvaluationFailsClosed() throws Exception {
        assertOutcomeInvalid("SUCCEEDED", "PLANNING_COMPLETED", """
                {"status":"SUCCEEDED",
                 "feasibilityReport":{"status":"VERIFIED","schemaVersion":1}}
                """);
    }

    @Test
    void failedPayloadWithReportFailsClosed() throws Exception {
        assertOutcomeInvalid("FAILED", "PLANNING_FAILED", """
                {"status":"FAILED","errorCode":"E",
                 "feasibilityReport":{"status":"VERIFIED","schemaVersion":1}}
                """);
    }

    @Test
    void cancelledPayloadWithEvaluationFailsClosed() throws Exception {
        assertOutcomeInvalid("CANCELLED", "PLANNING_CANCELLED", """
                {"status":"CANCELLED","evaluation":{"score":50}}
                """);
    }

    @Test
    void statusEventTypeMismatchFailsClosed() throws Exception {
        // task.status says WAITING_USER but the latest outcome event is a
        // completion: the read model must reject the contradiction.
        assertOutcomeInvalid("WAITING_USER", "PLANNING_COMPLETED", """
                {"status":"SUCCEEDED",
                 "feasibilityReport":{"status":"VERIFIED","schemaVersion":1},
                 "evaluation":{"score":90}}
                """);
    }

    @Test
    void reportObjectMissingRequiredFieldsFailsClosed() throws Exception {
        assertOutcomeInvalid("SUCCEEDED", "PLANNING_COMPLETED", """
                {"status":"SUCCEEDED",
                 "feasibilityReport":{"status":"VERIFIED"},
                 "evaluation":{"score":90}}
                """);
    }

    @Test
    void payloadArrayFailsClosed() throws Exception {
        assertOutcomeInvalid("FAILED", "PLANNING_FAILED", "[]");
    }

    // ── B6W FIX: latest planning task discovery ────────────────────────────

    @Test
    void latestReturnsTheNewestTaskForTheOwner() throws Exception {
        PlanningContext context = createPlanningContext("latest-newest@example.com");
        setTaskState(context, "FAILED", "PLANNING_FAILED", """
                {"status":"FAILED","errorCode":"STALE_TRIP_VERSION","message":"boom"}
                """);
        UUID secondTaskId = createTask(context);

        JsonNode latest = getLatestTask(context);

        assertThat(latest.path("taskId").asText()).isEqualTo(secondTaskId.toString());
    }

    @Test
    void latestTieBreaksByTaskIdWhenCreatedAtMatches() throws Exception {
        PlanningContext context = createPlanningContext("latest-tiebreak@example.com");
        UUID firstTaskId = context.taskId();
        setTaskState(context, "FAILED", "PLANNING_FAILED", """
                {"status":"FAILED","errorCode":"STALE_TRIP_VERSION","message":"boom"}
                """);
        UUID secondTaskId = createTask(context);
        jdbcTemplate.update(
                "UPDATE business.planning_task SET created_at = ? WHERE id IN (?, ?)",
                java.sql.Timestamp.from(java.time.Instant.now()), firstTaskId, secondTaskId);

        JsonNode latest = getLatestTask(context);

        // PostgreSQL orders uuid values as unsigned 16-byte big-endian, which
        // can disagree with Java UUID.compareTo (signed longs) once the most
        // significant byte crosses 0x80.  The production SQL is correct;
        // the expected value must use the database ordering semantics.
        UUID expected = compareAsPostgresUuid(firstTaskId, secondTaskId) > 0
                ? firstTaskId
                : secondTaskId;
        assertThat(latest.path("taskId").asText()).isEqualTo(expected.toString());
    }

    @Test
    void postgresUuidOrderingTreatsBothHalvesAsUnsigned() {
        // Most-significant end: Java compareTo sees 7fff... as positive and
        // 8000... as negative, so it orders 8000... first; PostgreSQL orders
        // 8000... after 7fff... (unsigned).  The helper must match the
        // database, not Java.
        UUID signedPositiveMost = UUID.fromString("7fffffff-ffff-ffff-ffff-ffffffffffff");
        UUID signedNegativeMost = UUID.fromString("80000000-0000-0000-0000-000000000000");
        assertThat(signedNegativeMost.compareTo(signedPositiveMost)).isLessThan(0);
        assertThat(compareAsPostgresUuid(signedNegativeMost, signedPositiveMost)).isGreaterThan(0);
        assertThat(compareAsPostgresUuid(signedPositiveMost, signedNegativeMost)).isLessThan(0);

        // Least-significant end: same unsigned-vs-signed disagreement once the
        // least significant long crosses 0x80.
        UUID signedPositiveLeast = UUID.fromString("00000000-0000-0000-7fff-ffffffffffff");
        UUID signedNegativeLeast = UUID.fromString("00000000-0000-0000-8000-000000000000");
        assertThat(signedNegativeLeast.compareTo(signedPositiveLeast)).isLessThan(0);
        assertThat(compareAsPostgresUuid(signedNegativeLeast, signedPositiveLeast)).isGreaterThan(0);
        assertThat(compareAsPostgresUuid(signedPositiveLeast, signedNegativeLeast)).isLessThan(0);
    }

    @Test
    void latestReturnsWaitingUserReviewOutcome() throws Exception {
        PlanningContext context = createPlanningContext("latest-review@example.com");
        reviewService.handle(reviewEvent(context, "review-v1-needs-repair-demo.json"));

        JsonNode latest = getLatestTask(context);

        assertThat(latest.path("status").asText()).isEqualTo("WAITING_USER");
        assertThat(latest.path("feasibilityReport").path("status").asText())
                .isEqualTo("NEEDS_REPAIR");
        assertThat(latest.path("candidateItinerary").path("title").asText())
                .isEqualTo("Benchmark itinerary");
        assertThat(latest.path("evaluation").isMissingNode()
                || latest.path("evaluation").isNull()).isTrue();
    }

    @Test
    void latestReturnsSucceededVerifiedOutcome() throws Exception {
        PlanningContext context = createPlanningContext("latest-succeeded@example.com");
        completionService.handle(completedEvent(context));

        JsonNode latest = getLatestTask(context);

        assertThat(latest.path("status").asText()).isEqualTo("SUCCEEDED");
        assertThat(latest.path("feasibilityReport").path("status").asText())
                .isEqualTo("VERIFIED");
        assertThat(latest.path("evaluation").isMissingNode()).isFalse();
        assertThat(latest.path("candidateItinerary").isMissingNode()
                || latest.path("candidateItinerary").isNull()).isTrue();
    }

    @Test
    void latestReturnsFailedState() throws Exception {
        PlanningContext context = createPlanningContext("latest-failed@example.com");
        setTaskState(context, "FAILED", "PLANNING_FAILED", """
                {"status":"FAILED","errorCode":"STALE_TRIP_VERSION","message":"boom"}
                """);

        JsonNode latest = getLatestTask(context);

        assertThat(latest.path("status").asText()).isEqualTo("FAILED");
        assertNoOutcomeFields(latest);
    }

    @Test
    void latestIsReadOnlyAndDoesNotCreateEvents() throws Exception {
        PlanningContext context = createPlanningContext("latest-readonly@example.com");
        Integer before = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM business.planning_task_event WHERE task_id = ?",
                Integer.class, context.taskId());

        getLatestTask(context);

        Integer after = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM business.planning_task_event WHERE task_id = ?",
                Integer.class, context.taskId());
        assertThat(after).isEqualTo(before);
    }

    @Test
    void latestReturns404ForAnotherOwnersTrip() throws Exception {
        PlanningContext context = createPlanningContext("latest-owner-a@example.com");
        String otherAccessToken = registerAndGetAccessToken("latest-owner-b@example.com");

        mockMvc.perform(get("/api/trips/{tripId}/planning-tasks/latest", context.tripId())
                        .header("Authorization", bearer(otherAccessToken)))
                .andExpect(status().isNotFound());
    }

    @Test
    void latestReturns404WhenNoTaskExists() throws Exception {
        String accessToken = registerAndGetAccessToken("latest-no-task@example.com");
        UUID tripId = createTrip(accessToken);

        mockMvc.perform(get("/api/trips/{tripId}/planning-tasks/latest", tripId)
                        .header("Authorization", bearer(accessToken)))
                .andExpect(status().isNotFound());
    }

    // ── helpers ───────────────────────────────────────────────────────────

    private void assertNoOutcomeFields(JsonNode task) {
        assertThat(task.path("feasibilityReport").isMissingNode()
                || task.path("feasibilityReport").isNull()).isTrue();
        assertThat(task.path("candidateItinerary").isMissingNode()
                || task.path("candidateItinerary").isNull()).isTrue();
        assertThat(task.path("evaluation").isMissingNode()
                || task.path("evaluation").isNull()).isTrue();
    }

    private void assertOutcomeInvalid(String taskStatus, String eventType, String payload)
            throws Exception {
        PlanningContext context = createPlanningContext("readmodel-invalid@example.com");
        UUID ownerId = jdbcTemplate.queryForObject(
                "SELECT id FROM business.user_account WHERE email = ?",
                UUID.class, "readmodel-invalid@example.com");
        jdbcTemplate.update(
                "UPDATE business.planning_task SET status = ? WHERE id = ?",
                taskStatus, context.taskId());
        jdbcTemplate.update("""
                INSERT INTO business.planning_task_event(
                    event_id, task_id, event_type, schema_version, payload, created_at
                ) VALUES (?, ?, ?, 1, CAST(? AS jsonb), now())
                """, UUID.randomUUID(), context.taskId(), eventType, payload);

        assertThatThrownBy(() -> planningTaskService.get(ownerId, context.taskId()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("Planning task terminal event is invalid");
    }

    private JsonNode getTask(PlanningContext context) throws Exception {
        MvcResult result = mockMvc.perform(get("/api/planning-tasks/{taskId}", context.taskId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andReturn();
        return objectMapper.readTree(result.getResponse().getContentAsString());
    }

    private UUID createTask(PlanningContext context) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .header("Idempotency-Key", UUID.randomUUID()))
                .andExpect(status().isAccepted())
                .andReturn();
        return UUID.fromString(json(result).get("taskId").asText());
    }

    private JsonNode getLatestTask(PlanningContext context) throws Exception {
        MvcResult result = mockMvc.perform(
                        get("/api/trips/{tripId}/planning-tasks/latest", context.tripId())
                                .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andReturn();
        return objectMapper.readTree(result.getResponse().getContentAsString());
    }

    private void setTaskState(PlanningContext context, String status,
                              String eventType, String payload) {
        jdbcTemplate.update(
                "UPDATE business.planning_task SET status = ? WHERE id = ?",
                status, context.taskId());
        jdbcTemplate.update("""
                INSERT INTO business.planning_task_event(
                    event_id, task_id, event_type, schema_version, payload, created_at
                ) VALUES (?, ?, ?, 1, CAST(? AS jsonb), now())
                """, UUID.randomUUID(), context.taskId(), eventType, payload);
    }

    private PlanningReviewRequiredEvent reviewEvent(
            PlanningContext context, String fixtureName
    ) throws Exception {
        String fixture = PlanningCompletedEventFixture.sharedReviewV1Fixture(fixtureName);
        JsonNode tree = objectMapper.readTree(fixture);
        ((ObjectNode) tree)
                .put("eventId", UUID.randomUUID().toString())
                .put("traceId", context.traceId().toString())
                .put("taskId", context.taskId().toString())
                .put("tripId", context.tripId().toString())
                .put("runId", UUID.randomUUID().toString());
        return reviewEventParser.parse(objectMapper.writeValueAsBytes(tree));
    }

    private PlanningCompletedEvent completedEvent(PlanningContext context) {
        return completedEventParser.parse(bytes(
                PlanningCompletedEventFixture.upgradeToV9(
                        PlanningCompletedEventFixture.completedEvent(
                                UUID.randomUUID(), context.traceId(),
                                context.taskId(), context.tripId()
                        )
                )
        ));
    }

    private byte[] bytes(String value) {
        return value.getBytes(StandardCharsets.UTF_8);
    }

    private PlanningContext createPlanningContext(String email) throws Exception {
        String accessToken = registerAndGetAccessToken(email);
        UUID tripId = createTrip(accessToken);
        MvcResult taskResult = mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", tripId)
                        .header("Authorization", bearer(accessToken))
                        .header("Idempotency-Key", UUID.randomUUID()))
                .andExpect(status().isAccepted())
                .andReturn();
        UUID taskId = UUID.fromString(json(taskResult).get("taskId").asText());
        UUID traceId = jdbcTemplate.queryForObject(
                "SELECT trace_id FROM business.planning_task WHERE id = ?", UUID.class, taskId
        );
        return new PlanningContext(accessToken, tripId, taskId, traceId);
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
        return objectMapper.readTree(result.getResponse().getContentAsString());
    }

    private String bearer(String token) {
        return "Bearer " + token;
    }

    /**
     * Orders two UUIDs the way PostgreSQL orders uuid values: unsigned
     * big-endian comparison of the 16 bytes.  Java's {@link UUID#compareTo}
     * uses signed longs, which reverses the order whenever the most
     * significant byte crosses 0x80.
     */
    private static int compareAsPostgresUuid(UUID left, UUID right) {
        int mostSignificant = Long.compareUnsigned(
                left.getMostSignificantBits(),
                right.getMostSignificantBits()
        );
        if (mostSignificant != 0) {
            return mostSignificant;
        }
        return Long.compareUnsigned(
                left.getLeastSignificantBits(),
                right.getLeastSignificantBits()
        );
    }
}
