package io.github.tobehardoo.trippilot.planning;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class PlanningTaskFlowIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private PlanningTaskService planningTaskService;

    @Autowired
    private PlatformTransactionManager transactionManager;

    @Test
    void cancelsAnOwnedTaskIdempotentlyAndReleasesTheActiveTaskConstraint() throws Exception {
        String accessToken = registerAndGetAccessToken("planning-cancel@example.com");
        String tripId = createTrip(accessToken);
        UUID taskId = UUID.fromString(json(createPlanningTask(
                accessToken, tripId, UUID.randomUUID()
        ).andExpect(status().isAccepted()).andReturn()).get("taskId").asText());

        for (int attempt = 0; attempt < 2; attempt++) {
            mockMvc.perform(delete("/api/planning-tasks/{taskId}", taskId)
                            .header("Authorization", bearer(accessToken)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.status").value("CANCELLED"));
        }
        createPlanningTask(accessToken, tripId, UUID.randomUUID())
                .andExpect(status().isAccepted());

        assertThat(jdbcTemplate.queryForObject(
                "SELECT count(*) FROM business.planning_task_event "
                        + "WHERE task_id = ? AND event_type = 'PLANNING_CANCELLED'",
                Integer.class, taskId
        )).isEqualTo(1);
        Map<String, Object> cancelOutbox = jdbcTemplate.queryForMap("""
                SELECT event_type, routing_key, payload ->> 'taskId' AS task_id
                FROM business.outbox_event
                WHERE aggregate_id = ? AND event_type = 'PLANNING_CANCEL_REQUESTED'
                """, taskId);
        assertThat(cancelOutbox).containsEntry("event_type", "PLANNING_CANCEL_REQUESTED")
                .containsEntry("routing_key", "planning.cancel")
                .containsEntry("task_id", taskId.toString());
    }

    @Test
    void createsQueuedTaskAndOutboxEventInOneRequest() throws Exception {
        String accessToken = registerAndGetAccessToken("planning-owner@example.com");
        String tripId = createTrip(accessToken);
        UUID idempotencyKey = UUID.randomUUID();

        MvcResult result = createPlanningTask(accessToken, tripId, idempotencyKey)
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.tripId").value(tripId))
                .andExpect(jsonPath("$.taskType").value("CREATE"))
                .andExpect(jsonPath("$.status").value("QUEUED"))
                .andExpect(jsonPath("$.baselineTripVersion").value(0))
                .andExpect(jsonPath("$.eventStreamUrl").isNotEmpty())
                .andReturn();

        JsonNode response = json(result);
        UUID taskId = UUID.fromString(response.get("taskId").asText());
        Map<String, Object> task = jdbcTemplate.queryForMap("""
                SELECT trip_id, idempotency_key, task_type, status, baseline_trip_version
                FROM business.planning_task
                WHERE id = ?
                """, taskId);
        Map<String, Object> outbox = jdbcTemplate.queryForMap("""
                SELECT aggregate_id, event_type, routing_key, status,
                       payload ->> 'eventId' AS event_id,
                       payload ->> 'taskId' AS task_id,
                       payload ->> 'tripId' AS trip_id,
                       payload #>> '{payload,trip,destination}' AS destination
                FROM business.outbox_event
                WHERE aggregate_id = ?
                """, taskId);

        assertThat(task).containsEntry("trip_id", UUID.fromString(tripId))
                .containsEntry("idempotency_key", idempotencyKey)
                .containsEntry("task_type", "CREATE")
                .containsEntry("status", "QUEUED")
                .containsEntry("baseline_trip_version", 0);
        assertThat(outbox).containsEntry("aggregate_id", taskId)
                .containsEntry("event_type", "PLANNING_CREATE_REQUESTED")
                .containsEntry("routing_key", "planning.create")
                .containsEntry("status", "PENDING")
                .containsEntry("task_id", taskId.toString())
                .containsEntry("trip_id", tripId)
                .containsEntry("destination", "广州");
        assertThat(outbox.get("event_id")).isNotNull();
    }

    @Test
    void repeatsAnIdempotentRequestWithoutDuplicatingTaskOrOutbox() throws Exception {
        String accessToken = registerAndGetAccessToken("planning-repeat@example.com");
        String tripId = createTrip(accessToken);
        UUID idempotencyKey = UUID.randomUUID();

        String firstTaskId = json(createPlanningTask(accessToken, tripId, idempotencyKey)
                .andExpect(status().isAccepted())
                .andReturn()).get("taskId").asText();
        String repeatedTaskId = json(createPlanningTask(accessToken, tripId, idempotencyKey)
                .andExpect(status().isAccepted())
                .andReturn()).get("taskId").asText();

        assertThat(repeatedTaskId).isEqualTo(firstTaskId);
        assertThat(count("business.planning_task")).isEqualTo(1);
        assertThat(count("business.outbox_event")).isEqualTo(1);
    }

    @Test
    void rejectsASecondActiveTaskForTheSameTrip() throws Exception {
        String accessToken = registerAndGetAccessToken("planning-active@example.com");
        String tripId = createTrip(accessToken);
        createPlanningTask(accessToken, tripId, UUID.randomUUID())
                .andExpect(status().isAccepted());

        createPlanningTask(accessToken, tripId, UUID.randomUUID())
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("PLANNING_TASK_ACTIVE"));

        assertThat(count("business.planning_task")).isEqualTo(1);
        assertThat(count("business.outbox_event")).isEqualTo(1);
    }

    @Test
    void hidesTripsOwnedByAnotherUserAndDoesNotCreateRecords() throws Exception {
        String ownerToken = registerAndGetAccessToken("planning-private-owner@example.com");
        String otherToken = registerAndGetAccessToken("planning-private-other@example.com");
        String tripId = createTrip(ownerToken);

        createPlanningTask(otherToken, tripId, UUID.randomUUID())
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("TRIP_NOT_FOUND"));

        assertThat(count("business.planning_task")).isZero();
        assertThat(count("business.outbox_event")).isZero();
    }

    @Test
    void requiresAnIdempotencyKey() throws Exception {
        String accessToken = registerAndGetAccessToken("planning-key@example.com");
        String tripId = createTrip(accessToken);

        mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", tripId)
                        .header("Authorization", bearer(accessToken)))
                .andExpect(status().isBadRequest());
    }

    @Test
    void rejectsPlanningForLegacyTripsLongerThanSevenDaysBeforeQueueing() throws Exception {
        String accessToken = registerAndGetAccessToken("planning-legacy-long@example.com");
        String tripId = createTrip(accessToken);
        jdbcTemplate.update(
                "UPDATE business.trip SET end_date = DATE '2026-08-08' WHERE id = ?",
                UUID.fromString(tripId)
        );

        createPlanningTask(accessToken, tripId, UUID.randomUUID())
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("TRIP_DURATION_UNSUPPORTED"));

        assertThat(count("business.planning_task")).isZero();
        assertThat(count("business.outbox_event")).isZero();
    }

    @Test
    void rollsBackTheTaskWhenTheOutboxInsertFails() throws Exception {
        String email = "planning-rollback@example.com";
        String accessToken = registerAndGetAccessToken(email);
        UUID tripId = UUID.fromString(createTrip(accessToken));
        UUID ownerId = ownerId(email);
        jdbcTemplate.execute("""
                CREATE FUNCTION business.fail_outbox_insert() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'forced outbox failure';
                END;
                $$ LANGUAGE plpgsql
                """);
        jdbcTemplate.execute("""
                CREATE TRIGGER fail_outbox_insert
                BEFORE INSERT ON business.outbox_event
                FOR EACH ROW EXECUTE FUNCTION business.fail_outbox_insert()
                """);

        RuntimeException failure = null;
        try {
            planningTaskService.create(ownerId, tripId, UUID.randomUUID());
        } catch (RuntimeException exception) {
            failure = exception;
        } finally {
            jdbcTemplate.execute("DROP TRIGGER fail_outbox_insert ON business.outbox_event");
            jdbcTemplate.execute("DROP FUNCTION business.fail_outbox_insert()");
        }

        assertThat(failure).isNotNull();
        assertThat(rootCause(failure)).hasMessageContaining("forced outbox failure");
        assertThat(count("business.planning_task")).isZero();
        assertThat(count("business.outbox_event")).isZero();
    }

    @Test
    void concurrentRequestsWithTheSameKeyReturnTheSameTask() throws Exception {
        String email = "planning-concurrent-repeat@example.com";
        String accessToken = registerAndGetAccessToken(email);
        UUID tripId = UUID.fromString(createTrip(accessToken));
        UUID ownerId = ownerId(email);
        UUID idempotencyKey = UUID.randomUUID();
        CountDownLatch start = new CountDownLatch(1);

        try (ExecutorService executor = Executors.newFixedThreadPool(2)) {
            Future<PlanningTaskService.PlanningTaskResponse> first = executor.submit(() -> {
                start.await();
                return planningTaskService.create(ownerId, tripId, idempotencyKey);
            });
            Future<PlanningTaskService.PlanningTaskResponse> second = executor.submit(() -> {
                start.await();
                return planningTaskService.create(ownerId, tripId, idempotencyKey);
            });
            start.countDown();

            assertThat(first.get(10, TimeUnit.SECONDS).taskId())
                    .isEqualTo(second.get(10, TimeUnit.SECONDS).taskId());
        }
        assertThat(count("business.planning_task")).isEqualTo(1);
        assertThat(count("business.outbox_event")).isEqualTo(1);
    }

    @Test
    void concurrentRequestsWithDifferentKeysAllowOnlyOneActiveTask() throws Exception {
        String email = "planning-concurrent-active@example.com";
        String accessToken = registerAndGetAccessToken(email);
        UUID tripId = UUID.fromString(createTrip(accessToken));
        UUID ownerId = ownerId(email);
        CountDownLatch start = new CountDownLatch(1);

        try (ExecutorService executor = Executors.newFixedThreadPool(2)) {
            Future<String> first = planningAttempt(executor, start, ownerId, tripId, UUID.randomUUID());
            Future<String> second = planningAttempt(executor, start, ownerId, tripId, UUID.randomUUID());
            start.countDown();

            assertThat(List.of(
                    first.get(10, TimeUnit.SECONDS), second.get(10, TimeUnit.SECONDS)
            ))
                    .containsExactlyInAnyOrder("ACCEPTED", "PLANNING_TASK_ACTIVE");
        }
        assertThat(count("business.planning_task")).isEqualTo(1);
        assertThat(count("business.outbox_event")).isEqualTo(1);
    }

    @Test
    void planningSnapshotRemainsConsistentDuringAConstraintUpdate() throws Exception {
        String email = "planning-snapshot@example.com";
        String accessToken = registerAndGetAccessToken(email);
        UUID ownerId = ownerId(email);
        TransactionTemplate transactions = new TransactionTemplate(transactionManager);

        for (int iteration = 0; iteration < 12; iteration++) {
            UUID tripId = UUID.fromString(createTrip(accessToken));
            CountDownLatch start = new CountDownLatch(1);
            try (ExecutorService executor = Executors.newFixedThreadPool(2)) {
                Future<?> update = executor.submit(() -> {
                    start.await();
                    transactions.executeWithoutResult(status -> {
                        jdbcTemplate.update("UPDATE business.trip SET version = 1 WHERE id = ?", tripId);
                        jdbcTemplate.update(
                                "UPDATE business.trip_constraint SET travelers = 3 WHERE trip_id = ?", tripId
                        );
                    });
                    return null;
                });
                Future<?> planning = executor.submit(() -> {
                    start.await();
                    planningTaskService.create(ownerId, tripId, UUID.randomUUID());
                    return null;
                });
                start.countDown();
                update.get(10, TimeUnit.SECONDS);
                planning.get(10, TimeUnit.SECONDS);
            }

            Map<String, Object> snapshot = jdbcTemplate.queryForMap("""
                    SELECT payload #>> '{payload,trip,version}' AS version,
                           payload #>> '{payload,trip,constraints,travelers}' AS travelers
                    FROM business.outbox_event
                    WHERE aggregate_id IN (
                        SELECT id FROM business.planning_task WHERE trip_id = ?
                    )
                    """, tripId);
            int version = Integer.parseInt((String) snapshot.get("version"));
            int travelers = Integer.parseInt((String) snapshot.get("travelers"));
            assertThat(Map.entry(version, travelers))
                    .isIn(Map.entry(0, 2), Map.entry(1, 3));
        }
    }

    @Test
    void planningCommandSnapshotsOnlyEnabledFreshGuideFacts() throws Exception {
        String accessToken = registerAndGetAccessToken("planning-guide-evidence@example.com");
        UUID tripId = UUID.fromString(createTrip(accessToken));
        UUID enabledImport = UUID.randomUUID();
        UUID disabledImport = UUID.randomUUID();
        UUID expiredImport = UUID.randomUUID();
        insertGuideImport(enabledImport, tripId, "fresh", true);
        insertGuideImport(disabledImport, tripId, "disabled", false);
        insertGuideImport(expiredImport, tripId, "expired", true);
        insertGuideFact(enabledImport, "新鲜事实", "2099-08-01T00:00:00Z");
        insertGuideFact(disabledImport, "停用事实", "2099-08-01T00:00:00Z");
        insertGuideFact(expiredImport, "过期事实", "2020-08-01T00:00:00Z");

        createPlanningTask(accessToken, tripId.toString(), UUID.randomUUID())
                .andExpect(status().isAccepted());

        Map<String, Object> snapshot = jdbcTemplate.queryForMap("""
                SELECT payload #>> '{schemaVersion}' AS schema_version,
                       payload #>> '{payload,guideEvidence,facts,0,statement}' AS statement,
                       jsonb_array_length(payload #> '{payload,guideEvidence,facts}') AS fact_count,
                       (
                         SELECT guide_evidence_snapshot #>> '{facts,0,statement}'
                         FROM business.planning_task
                         WHERE id = outbox_event.aggregate_id
                       ) AS durable_statement
                FROM business.outbox_event
                WHERE event_type = 'PLANNING_CREATE_REQUESTED'
                """);
        assertThat(snapshot.get("schema_version")).isEqualTo("2");
        assertThat(snapshot.get("statement")).isEqualTo("新鲜事实");
        assertThat(snapshot.get("fact_count")).isEqualTo(1);
        assertThat(snapshot.get("durable_statement")).isEqualTo(snapshot.get("statement"));

        jdbcTemplate.update(
                "UPDATE business.guide_fact SET statement = 'changed after task' "
                        + "WHERE guide_import_id = ?",
                enabledImport
        );
        jdbcTemplate.update(
                "DELETE FROM business.outbox_event "
                        + "WHERE event_type = 'PLANNING_CREATE_REQUESTED'"
        );
        String retainedStatement = jdbcTemplate.queryForObject("""
                SELECT guide_evidence_snapshot #>> '{facts,0,statement}'
                FROM business.planning_task
                """, String.class);
        assertThat(retainedStatement).isEqualTo(snapshot.get("statement"));
    }

    private void insertGuideImport(UUID id, UUID tripId, String suffix, boolean enabled) {
        jdbcTemplate.update("""
                INSERT INTO business.guide_import(
                    id, trip_id, source_url, final_url, source_host, title,
                    excerpt, content_hash, fetched_at, enabled
                ) VALUES (?, ?, ?, ?, 'example.com', ?, 'excerpt', ?, CURRENT_TIMESTAMP, ?)
                """,
                id,
                tripId,
                "https://example.com/" + suffix,
                "https://example.com/" + suffix,
                "Guide " + suffix,
                String.valueOf(suffix.charAt(0)).repeat(64),
                enabled
        );
    }

    private void insertGuideFact(UUID guideImportId, String statement, String expiresAt) {
        jdbcTemplate.update("""
                INSERT INTO business.guide_fact(
                    id, guide_import_id, category, statement, evidence,
                    confidence, observed_at, expires_at
                ) VALUES (
                    ?, ?, 'ATTRACTION', ?, ?, 0.8,
                    LEAST(
                        '2026-07-01T00:00:00Z'::timestamptz,
                        ?::timestamptz - interval '1 day'
                    ),
                    ?::timestamptz
                )
                """,
                UUID.randomUUID(), guideImportId, statement, statement, expiresAt, expiresAt
        );
    }

    private org.springframework.test.web.servlet.ResultActions createPlanningTask(
            String accessToken, String tripId, UUID idempotencyKey) throws Exception {
        return mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", tripId)
                .header("Authorization", bearer(accessToken))
                .header("Idempotency-Key", idempotencyKey));
    }

    private String createTrip(String accessToken) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "广州四日慢游",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-04",
                                  "constraints": {
                                    "budgetAmount": 6000,
                                    "travelers": 2,
                                    "travelerType": "FRIENDS",
                                    "pace": "BALANCED",
                                    "preferences": ["美食", "历史"],
                                    "fixedSchedules": []
                                  }
                                }
                                """))
                .andExpect(status().isCreated())
                .andReturn();
        return json(result).get("id").asText();
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

    private int count(String table) {
        Integer count = jdbcTemplate.queryForObject("SELECT count(*) FROM " + table, Integer.class);
        return count == null ? 0 : count;
    }

    private UUID ownerId(String email) {
        return jdbcTemplate.queryForObject(
                "SELECT id FROM business.user_account WHERE email = ?", UUID.class, email
        );
    }

    private Future<String> planningAttempt(ExecutorService executor, CountDownLatch start,
                                           UUID ownerId, UUID tripId, UUID idempotencyKey) {
        return executor.submit(() -> {
            start.await();
            try {
                planningTaskService.create(ownerId, tripId, idempotencyKey);
                return "ACCEPTED";
            } catch (ApiException exception) {
                return exception.code();
            }
        });
    }

    private Throwable rootCause(Throwable failure) {
        Throwable result = failure;
        while (result.getCause() != null) {
            result = result.getCause();
        }
        return result;
    }

    private JsonNode json(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsByteArray());
    }

    private String bearer(String accessToken) {
        return "Bearer " + accessToken;
    }
}
