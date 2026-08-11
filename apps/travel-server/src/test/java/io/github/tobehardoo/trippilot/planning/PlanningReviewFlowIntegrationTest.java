package io.github.tobehardoo.trippilot.planning;

import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEventParser;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningReviewRequiredEvent;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningReviewRequiredEventParser;
import io.github.tobehardoo.trippilot.itinerary.ItineraryService;
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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Real database round-trip for PLANNING_REVIEW_REQUIRED:
 * validated event -&gt; service -&gt; task lock -&gt; WAITING_USER -&gt;
 * planning_task_event JSONB -&gt; read back and deep-compare.
 */
class PlanningReviewFlowIntegrationTest extends PostgresIntegrationTest {

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
    private ItineraryService itineraryService;

    private record PlanningContext(
            String accessToken, UUID tripId, UUID taskId, UUID traceId, int taskVersion
    ) {
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
        int taskVersion = jdbcTemplate.queryForObject(
                "SELECT version FROM business.planning_task WHERE id = ?", Integer.class, taskId
        );
        return new PlanningContext(accessToken, tripId, taskId, traceId, taskVersion);
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

    private void updateConstraints(String accessToken, UUID tripId, int travelers) throws Exception {
        mockMvc.perform(put("/api/trips/{tripId}/constraints", tripId)
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "version": 0,
                                  "budgetAmount": 1000,
                                  "travelers": %d,
                                  "travelerType": "FRIENDS",
                                  "pace": "BALANCED",
                                  "preferences": ["美食"],
                                  "fixedSchedules": []
                                }
                                """.formatted(travelers)))
                .andExpect(status().isOk());
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

    private String taskErrorCode(UUID taskId) {
        return jdbcTemplate.queryForObject(
                "SELECT error_code FROM business.planning_task WHERE id = ?", String.class, taskId);
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

    private long count(String table) {
        return jdbcTemplate.queryForObject(
                "SELECT count(*) FROM " + table, Long.class);
    }

    // ── F1/F2: normal review DB round-trip ─────────────────────────────────

    @Test
    void persistsCompleteReviewOutcomeToDatabaseAndReadsItBack() throws Exception {
        PlanningContext context = createPlanningContext("review-roundtrip@example.com");
        PlanningReviewRequiredEvent event = reviewEvent(
                context, "review-v1-needs-repair-demo.json");

        reviewService.handle(event);

        // 1. Task is WAITING_USER with incremented version.
        assertThat(taskStatus(context.taskId())).isEqualTo("WAITING_USER");
        int newVersion = jdbcTemplate.queryForObject(
                "SELECT version FROM business.planning_task WHERE id = ?",
                Integer.class, context.taskId());
        assertThat(newVersion).isEqualTo(context.taskVersion() + 1);

        // 2. Task event row exists with correct envelope.
        Map<String, Object> row = jdbcTemplate.queryForMap("""
                SELECT event_id, task_id, event_type, schema_version, payload::text AS payload
                FROM business.planning_task_event
                WHERE event_id = ?
                """, event.eventId());
        assertThat(row.get("task_id")).isEqualTo(context.taskId());
        assertThat(row.get("event_type")).isEqualTo("PLANNING_REVIEW_REQUIRED");
        assertThat(row.get("schema_version")).isEqualTo(1);

        // 3. Deep-compare the stored payload (not string contains).
        JsonNode stored = objectMapper.readTree((String) row.get("payload"));
        assertThat(stored.path("status").asText()).isEqualTo("WAITING_USER");
        assertThat(stored.path("runId").asText()).isEqualTo(event.runId().toString());
        assertThat(stored.path("provider").asText()).isEqualTo("DEMO");

        // candidateItinerary deep compare against the original event itinerary.
        JsonNode candidate = stored.path("candidateItinerary");
        assertThat(candidate.path("title").asText())
                .isEqualTo(event.payload().itinerary().title());
        assertThat(candidate.path("days")).hasSize(1);
        assertThat(candidate.path("days").get(0).path("date").asText()).isEqualTo("2026-08-01");
        assertThat(candidate.path("days").get(0).path("activities")).hasSize(2);
        assertThat(candidate.path("estimatedTotalCost").asText())
                .isEqualTo(event.payload().itinerary().estimatedTotalCost().toPlainString());

        // knowledge deep compare.
        JsonNode knowledge = stored.path("knowledge");
        assertThat(knowledge.path("status").asText()).isEqualTo("REAL");
        assertThat(knowledge.path("citations")).hasSize(1);
        assertThat(knowledge.path("freshness").path("status").asText()).isEqualTo("FRESH");

        // factImpacts / providerProvenance present.
        assertThat(stored.path("factImpacts").isArray()).isTrue();
        assertThat(stored.has("providerProvenance")).isTrue();

        // 4. Full feasibilityReport: summary, ruleResults, evidenceRefs,
        //    repairAttempts read back losslessly.
        JsonNode report = stored.path("feasibilityReport");
        assertThat(report.path("status").asText()).isEqualTo("NEEDS_REPAIR");
        assertThat(report.path("schemaVersion").asInt()).isEqualTo(1);
        assertThat(report.path("summary").path("totalCount").asInt()).isEqualTo(11);
        assertThat(report.path("summary").path("failCount").asInt()).isEqualTo(1);
        assertThat(report.path("ruleResults")).hasSize(11);
        assertThat(report.path("repairAttempts")).hasSize(1);
        assertThat(report.path("repairAttempts").get(0).path("attemptIndex").asInt())
                .isEqualTo(1);
        JsonNode openingResult = null;
        for (JsonNode rule : report.path("ruleResults")) {
            if ("OPENING_HOURS".equals(rule.path("ruleId").asText())) {
                openingResult = rule;
            }
        }
        assertThat(openingResult).isNotNull();
        // Non-empty EvidenceReference survives the parser -> service ->
        // JSONB -> read-back round trip, field by field.
        assertThat(openingResult.path("evidenceRefs")).hasSize(1);
        JsonNode evidence = openingResult.path("evidenceRefs").get(0);
        assertThat(evidence.path("evidenceId").asText()).isEqualTo("opening-stale-001");
        assertThat(evidence.path("evidenceType").asText()).isEqualTo("OPENING_HOURS");
        assertThat(evidence.path("state").asText()).isEqualTo("STALE");
        assertThat(evidence.path("hardConstraintEligible").asBoolean()).isFalse();
        assertThat(openingResult.path("outcome").asText()).isEqualTo("UNKNOWN");

        // 5. Candidate itinerary fingerprint corresponds to the report.
        String storedFingerprint = report.path("itineraryFingerprint").asText();
        assertThat(storedFingerprint).matches("^[0-9a-f]{64}$");
        assertThat(storedFingerprint)
                .isEqualTo(event.payload().feasibilityReport().itineraryFingerprint());

        // 6. No itinerary version, no current version change, no formal report row.
        assertThat(count("business.itinerary_version")).isZero();
        // The trip has no itinerary row at all: review never created one and
        // never touched a current version.
        assertThat(count("business.itinerary")).isZero();
        assertThat(count("business.itinerary_feasibility_report")).isZero();

        // The committed task_event row is readable through an independent
        // query after the service transaction completed (QUEUED + REVIEW).
        // This does not assert Spring after-commit callbacks or SSE publish;
        // those belong to the J6 read-model batch.
        assertThat(count("business.planning_task_event")).isEqualTo(2L);
    }

    // ── F3 scenario A: stale trip baseline ────────────────────────────────

    @Test
    void staleTripBaselineFailsTaskWithStaleTripVersion() throws Exception {
        PlanningContext context = createPlanningContext("review-stale-trip@example.com");
        // Bump the trip version after the planning task captured its baseline.
        updateConstraints(context.accessToken(), context.tripId(), 3);

        // Explicit pre-condition from the database: the task baseline must
        // differ from the trip's current version before the review arrives.
        int baselineTripVersion = jdbcTemplate.queryForObject(
                "SELECT baseline_trip_version FROM business.planning_task WHERE id = ?",
                Integer.class, context.taskId());
        int currentTripVersion = jdbcTemplate.queryForObject(
                "SELECT version FROM business.trip WHERE id = ?",
                Integer.class, context.tripId());
        assertThat(baselineTripVersion)
                .as("stale trip baseline precondition: baseline must differ from current")
                .isNotEqualTo(currentTripVersion);

        PlanningReviewRequiredEvent event = reviewEvent(
                context, "review-v1-needs-repair-demo.json");
        reviewService.handle(event);

        assertThat(taskStatus(context.taskId())).isEqualTo("FAILED");
        assertThat(taskErrorCode(context.taskId())).isEqualTo("STALE_TRIP_VERSION");
        Map<String, Object> failedEvent = jdbcTemplate.queryForMap("""
                SELECT event_type, payload::text AS payload
                FROM business.planning_task_event
                WHERE task_id = ? AND event_type = 'PLANNING_FAILED'
                ORDER BY id DESC LIMIT 1
                """, context.taskId());
        assertThat(failedEvent.get("event_type")).isEqualTo("PLANNING_FAILED");
        JsonNode payload = objectMapper.readTree((String) failedEvent.get("payload"));
        assertThat(payload.path("status").asText()).isEqualTo("FAILED");
        assertThat(payload.path("errorCode").asText()).isEqualTo("STALE_TRIP_VERSION");
        assertThat(count("business.itinerary_version")).isZero();
        assertThat(count("business.itinerary")).isZero();
    }

    // ── F3 scenario B: stale replan itinerary baseline ────────────────────

    @Test
    void staleReplanBaselineFailsTaskWithStaleItineraryVersion() throws Exception {
        PlanningContext context = createPlanningContext("review-stale-replan@example.com");
        // 1. Complete a first v9 itinerary so the trip has a current version.
        io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent completed =
                completedEventParser.parse(
                        PlanningCompletedEventFixture.upgradeToV9(
                                PlanningCompletedEventFixture.completedAmapEventV3(
                                        UUID.randomUUID(), context.traceId(),
                                        context.taskId(), context.tripId()
                                )
                        ).getBytes(StandardCharsets.UTF_8));
        completionService.handle(completed);
        UUID firstVersionId = jdbcTemplate.queryForObject("""
                SELECT current_version_id FROM business.itinerary WHERE trip_id = ?
                """, UUID.class, context.tripId());
        assertThat(firstVersionId).isNotNull();

        // 2. Create a REPLAN task pinned to the first version by inserting the
        //    task directly (mirrors the API-created replan task shape).
        UUID replanTaskId = UUID.randomUUID();
        UUID replanTraceId = UUID.randomUUID();
        jdbcTemplate.update("""
                INSERT INTO business.planning_task(
                    id, trip_id, idempotency_key, task_type, status,
                    baseline_trip_version, baseline_itinerary_version_id,
                    impacted_dates, constraint_snapshot, guide_evidence_snapshot,
                    trace_id, retry_count, version
                ) VALUES (
                    ?, ?, ?, 'REPLAN', 'RUNNING',
                    (SELECT version FROM business.trip WHERE id = ?), ?,
                    CAST('["2026-08-01"]' AS jsonb), CAST('{}' AS jsonb),
                    CAST('{}' AS jsonb), ?, 0, 3
                )
                """,
                replanTaskId, context.tripId(), UUID.randomUUID(), context.tripId(),
                firstVersionId, replanTraceId);
        PlanningContext replanContext = new PlanningContext(
                context.accessToken(), context.tripId(), replanTaskId, replanTraceId, 3);

        // 3. Switch current itinerary to a newer version, simulating a
        //    concurrent replan that finished after this task captured its
        //    baseline.  The planning_task unique-per-trip constraint means no
        //    second task row can exist, so the version switch is applied
        //    directly at the DB level (the exact state a racing replan
        //    completion would produce).
        UUID secondVersionId = UUID.randomUUID();
        jdbcTemplate.update("""
                INSERT INTO business.itinerary_version(
                    id, itinerary_id, version_number, parent_version_id,
                    planning_task_id, version_source, title, estimated_total_cost,
                    provider, constraint_snapshot, created_at
                ) VALUES (
                    ?, (SELECT id FROM business.itinerary WHERE trip_id = ?), 2,
                    ?, NULL, 'LOCAL_REPLAN', 'Newer', 0, 'AMAP',
                    CAST('{}' AS jsonb), now()
                )
                """, secondVersionId, context.tripId(), firstVersionId);
        jdbcTemplate.update("""
                UPDATE business.itinerary SET current_version_id = ?
                WHERE trip_id = ?
                """, secondVersionId, context.tripId());
        assertThat(jdbcTemplate.queryForObject("""
                SELECT current_version_id FROM business.itinerary WHERE trip_id = ?
                """, UUID.class, context.tripId())).isEqualTo(secondVersionId);
        assertThat(secondVersionId).isNotEqualTo(firstVersionId);

        // 4. Review arrives for the replan task with stale baseline.
        PlanningReviewRequiredEvent review = reviewEvent(
                replanContext, "review-v1-needs-repair-demo.json");
        reviewService.handle(review);

        assertThat(taskStatus(replanTaskId)).isEqualTo("FAILED");
        assertThat(taskErrorCode(replanTaskId)).isEqualTo("STALE_ITINERARY_VERSION");
        Map<String, Object> failedEvent = jdbcTemplate.queryForMap("""
                SELECT event_type, payload::text AS payload
                FROM business.planning_task_event
                WHERE task_id = ? AND event_type = 'PLANNING_FAILED'
                ORDER BY id DESC LIMIT 1
                """, replanTaskId);
        assertThat(failedEvent.get("event_type")).isEqualTo("PLANNING_FAILED");
        JsonNode payload = objectMapper.readTree((String) failedEvent.get("payload"));
        assertThat(payload.path("errorCode").asText()).isEqualTo("STALE_ITINERARY_VERSION");
        // Current version stays at the second version; review created nothing.
        assertThat(jdbcTemplate.queryForObject("""
                SELECT current_version_id FROM business.itinerary WHERE trip_id = ?
                """, UUID.class, context.tripId())).isEqualTo(secondVersionId);
        // Only the two versions we created exist; review added none.
        long versionCount = count("business.itinerary_version");
        assertThat(versionCount).isEqualTo(2L);
    }

    // ── F3: report insert failure rollback ────────────────────────────────

    @Test
    void reportInsertFailureRollsBackTheWholeCompletionTransaction() throws Exception {
        PlanningContext context = createPlanningContext("completion-report-fail@example.com");
        jdbcTemplate.execute("""
                CREATE FUNCTION business.fail_report_insert() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'forced report failure';
                END;
                $$ LANGUAGE plpgsql
                """);
        jdbcTemplate.execute("""
                CREATE TRIGGER fail_report_insert
                BEFORE INSERT ON business.itinerary_feasibility_report
                FOR EACH ROW EXECUTE FUNCTION business.fail_report_insert()
                """);

        try {
            io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent event =
                    completedEventParser.parse(
                            PlanningCompletedEventFixture.upgradeToV9(
                                    PlanningCompletedEventFixture.completedAmapEventV3(
                                            UUID.randomUUID(), context.traceId(),
                                            context.taskId(), context.tripId()
                                    )
                            ).getBytes(StandardCharsets.UTF_8));
            assertThatThrownBy(() -> completionService.handle(event))
                    .rootCause()
                    .hasMessageContaining("forced report failure");
        } finally {
            jdbcTemplate.execute(
                    "DROP TRIGGER fail_report_insert ON business.itinerary_feasibility_report");
            jdbcTemplate.execute("DROP FUNCTION business.fail_report_insert()");
        }

        // Whole transaction rolled back: no version, no report, no terminal
        // event, task back to its pre-completion state.
        assertThat(count("business.itinerary")).isZero();
        assertThat(count("business.itinerary_version")).isZero();
        assertThat(count("business.itinerary_day")).isZero();
        assertThat(count("business.activity")).isZero();
        assertThat(count("business.itinerary_feasibility_report")).isZero();
        assertThat(count("business.planning_task_event")).isEqualTo(1L);
        assertThat(taskStatus(context.taskId())).isEqualTo("QUEUED");
    }
}
