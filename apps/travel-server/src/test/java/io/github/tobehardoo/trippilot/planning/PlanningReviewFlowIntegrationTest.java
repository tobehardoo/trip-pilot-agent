package io.github.tobehardoo.trippilot.planning;

import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEventParser;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningProgressEventParser;
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
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.not;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
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
    private PlanningTaskService planningTaskService;

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

    // ── R6: task_event insert failure rolls back the whole review ─────────

    @Test
    void taskEventInsertFailureRollsBackTheWholeReviewTransaction() throws Exception {
        PlanningContext context = createPlanningContext("review-event-fail@example.com");
        jdbcTemplate.execute("""
                CREATE FUNCTION business.fail_task_event_insert() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'forced task event failure';
                END;
                $$ LANGUAGE plpgsql
                """);
        jdbcTemplate.execute("""
                CREATE TRIGGER fail_task_event_insert
                BEFORE INSERT ON business.planning_task_event
                FOR EACH ROW EXECUTE FUNCTION business.fail_task_event_insert()
                """);

        try {
            PlanningReviewRequiredEvent event = reviewEvent(
                    context, "review-v1-needs-repair-demo.json");
            assertThatThrownBy(() -> reviewService.handle(event))
                    .rootCause()
                    .hasMessageContaining("forced task event failure");
        } finally {
            jdbcTemplate.execute(
                    "DROP TRIGGER fail_task_event_insert ON business.planning_task_event");
            jdbcTemplate.execute("DROP FUNCTION business.fail_task_event_insert()");
        }

        // Whole review transaction rolled back: task stays QUEUED at its
        // original version, only the original QUEUED event remains, and no
        // itinerary/version/report was created.
        assertThat(taskStatus(context.taskId())).isEqualTo("QUEUED");
        assertThat(jdbcTemplate.queryForObject(
                "SELECT version FROM business.planning_task WHERE id = ?",
                Integer.class, context.taskId())).isEqualTo(context.taskVersion());
        assertThat(count("business.planning_task_event")).isEqualTo(1L);
        assertThat(count("business.itinerary")).isZero();
        assertThat(count("business.itinerary_version")).isZero();
        assertThat(count("business.itinerary_feasibility_report")).isZero();
    }

    // ── B6J.2.1 F1: service-level gate rejects invalid v4 reports ─────────

    @Test
    void serviceRejectsInvalidV4ReportEvenWhenCalledDirectly() throws Exception {
        PlanningContext context = createPlanningContext("review-direct-invalid-ref@example.com");
        PlanningReviewRequiredEvent event = reviewEventWithoutParserValidation(
                context, "review-v1-needs-repair-demo.json",
                node -> {
                    com.fasterxml.jackson.databind.JsonNode results =
                            node.at("/payload/feasibilityReport/ruleResults");
                    for (com.fasterxml.jackson.databind.JsonNode rule : results) {
                        if (rule.path("affectedEntityRefs").isArray()
                                && rule.path("affectedEntityRefs").size() > 0) {
                            ((com.fasterxml.jackson.databind.node.ArrayNode)
                                    rule.path("affectedEntityRefs"))
                                    .set(0, objectMapper.getNodeFactory()
                                            .textNode("8f5ef9c2-c194-4292-b847-5b9dcfda978b"));
                            return;
                        }
                    }
                    com.fasterxml.jackson.databind.node.ArrayNode refs =
                            objectMapper.createArrayNode();
                    refs.add("8f5ef9c2-c194-4292-b847-5b9dcfda978b");
                    ((com.fasterxml.jackson.databind.node.ObjectNode) results.get(0))
                            .set("affectedEntityRefs", refs);
                });

        assertThatThrownBy(() -> reviewService.handle(event))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("feasibility report is invalid");
        assertThat(taskStatus(context.taskId())).isEqualTo("QUEUED");
        assertThat(count("business.planning_task_event")).isEqualTo(1L);
    }

    @Test
    void serviceRejectsUnknownValidatorVersionEvenWhenCalledDirectly() throws Exception {
        PlanningContext context = createPlanningContext("review-direct-unknown-version@example.com");
        PlanningReviewRequiredEvent event = reviewEventWithoutParserValidation(
                context, "review-v1-needs-repair-demo.json",
                node -> ((com.fasterxml.jackson.databind.node.ObjectNode)
                        node.at("/payload/feasibilityReport"))
                        .put("validatorVersion", "hard-validator-v9"));

        assertThatThrownBy(() -> reviewService.handle(event))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("feasibility report is invalid");
        assertThat(taskStatus(context.taskId())).isEqualTo("QUEUED");
        assertThat(count("business.planning_task_event")).isEqualTo(1L);
    }

    // ── B6J.2.2 R2: lossless raw candidate storage ────────────────────────

    @Test
    void storedCandidateDeepEqualsWireItineraryAndBindsFingerprint() throws Exception {
        PlanningContext context = createPlanningContext("review-raw-candidate@example.com");
        String fixture = PlanningCompletedEventFixture.sharedReviewV1Fixture(
                "review-v1-needs-repair-demo.json");
        JsonNode wireItinerary = objectMapper.readTree(fixture).at("/payload/itinerary");

        reviewService.handle(reviewEvent(context, "review-v1-needs-repair-demo.json"));

        Map<String, Object> row = jdbcTemplate.queryForMap("""
                SELECT payload::text AS payload
                FROM business.planning_task_event
                WHERE task_id = ? AND event_type = 'PLANNING_REVIEW_REQUIRED'
                ORDER BY id DESC LIMIT 1
                """, context.taskId());
        JsonNode storedPayload = objectMapper.readTree((String) row.get("payload"));
        JsonNode storedCandidate = storedPayload.path("candidateItinerary");

        // The stored candidate must be byte-identical to the validated wire
        // itinerary (no DTO round-trip mutation: no costSource defaulting,
        // no BigDecimal normalisation, no invented null fields).
        assertThat(storedCandidate).isEqualTo(wireItinerary);

        // The report fingerprint must bind the stored candidate.
        String reportFingerprint = storedPayload
                .path("feasibilityReport").path("itineraryFingerprint").asText();
        assertThat(io.github.tobehardoo.trippilot.feasibility.ItineraryFingerprintVerifier
                .matches(storedCandidate, reportFingerprint)).isTrue();
    }

    // ── B6J.2.2 R3: DB tampering fails closed ─────────────────────────────

    @Test
    void tamperedStoredCandidateFailsClosedOnTaskApi() throws Exception {
        PlanningContext context = createPlanningContext("review-tamper-candidate@example.com");
        reviewService.handle(reviewEvent(context, "review-v1-needs-repair-demo.json"));
        UUID ownerId = jdbcTemplate.queryForObject(
                "SELECT id FROM business.user_account WHERE email = ?",
                UUID.class, "review-tamper-candidate@example.com");

        // Control group: untouched task reads back WAITING_USER.
        assertThat(planningTaskService.get(ownerId, context.taskId()).status())
                .isEqualTo("WAITING_USER");

        // Tamper with a fingerprint-participating field of the stored
        // candidate (activity title), leaving the report unchanged.
        jdbcTemplate.update("""
                UPDATE business.planning_task_event
                SET payload = jsonb_set(
                        payload,
                        '{candidateItinerary,days,0,activities,0,title}',
                        '"tampered"'
                    )
                WHERE task_id = ? AND event_type = 'PLANNING_REVIEW_REQUIRED'
                """, context.taskId());

        assertThatThrownBy(() -> planningTaskService.get(ownerId, context.taskId()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("Planning task terminal event is invalid");
    }

    @Test
    void tamperedStoredFingerprintFailsClosedOnTaskApi() throws Exception {
        PlanningContext context = createPlanningContext("review-tamper-fp@example.com");
        reviewService.handle(reviewEvent(context, "review-v1-needs-repair-demo.json"));
        UUID ownerId = jdbcTemplate.queryForObject(
                "SELECT id FROM business.user_account WHERE email = ?",
                UUID.class, "review-tamper-fp@example.com");

        // Replace the stored report fingerprint with another valid 64-hex
        // value that no longer matches the candidate.
        String tamperedFingerprint = "1".repeat(64);
        jdbcTemplate.update("""
                UPDATE business.planning_task_event
                SET payload = jsonb_set(
                        payload,
                        '{feasibilityReport,itineraryFingerprint}',
                        CAST(? AS jsonb)
                    )
                WHERE task_id = ? AND event_type = 'PLANNING_REVIEW_REQUIRED'
                """, "\"" + tamperedFingerprint + "\"", context.taskId());

        assertThatThrownBy(() -> planningTaskService.get(ownerId, context.taskId()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("Planning task terminal event is invalid");
    }

    // ── B6J.2.2 R4: service bypass integrity gates ────────────────────────

    @Test
    void serviceRejectsBypassEventWithoutRawCandidateSnapshot() throws Exception {
        PlanningContext context = createPlanningContext("review-bypass-no-snapshot@example.com");
        // treeToValue constructs an event without the internal raw snapshot.
        PlanningReviewRequiredEvent event = reviewEventWithoutParserValidation(
                context, "review-v1-needs-repair-demo.json", node -> {
                });

        assertThatThrownBy(() -> reviewService.handle(event))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("validated itinerary");
        assertThat(taskStatus(context.taskId())).isEqualTo("QUEUED");
        assertThat(count("business.planning_task_event")).isEqualTo(1L);
    }

    @Test
    void serviceRejectsBypassEventWithFingerprintMismatch() throws Exception {
        PlanningContext context = createPlanningContext("review-bypass-fp-mismatch@example.com");
        PlanningReviewRequiredEvent event = reviewEventWithoutParserValidationWithSnapshot(
                context, "review-v1-needs-repair-demo.json",
                node -> ((com.fasterxml.jackson.databind.node.ObjectNode)
                        node.at("/payload/feasibilityReport"))
                        .put("itineraryFingerprint", "0".repeat(64)));

        assertThatThrownBy(() -> reviewService.handle(event))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("does not match the report fingerprint");
        assertThat(taskStatus(context.taskId())).isEqualTo("QUEUED");
        assertThat(count("business.planning_task_event")).isEqualTo(1L);
    }

    @Test
    void serviceRejectsBypassEventWithRawTypedInconsistency() throws Exception {
        PlanningContext context = createPlanningContext("review-bypass-inconsistent@example.com");
        // Any raw mutation (here the title) changes the fingerprint first,
        // so the integrity gate rejects before any state change.  The raw
        // snapshot is bound to the report fingerprint, so a raw/typed
        // inconsistency cannot survive the fingerprint gate.
        PlanningReviewRequiredEvent event = reviewEventWithoutParserValidationWithSnapshot(
                context, "review-v1-needs-repair-demo.json",
                node -> ((com.fasterxml.jackson.databind.node.ObjectNode)
                        node.at("/payload/itinerary")).put("title", "raw-mutated"));

        assertThatThrownBy(() -> reviewService.handle(event))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("does not match the report fingerprint");
        assertThat(taskStatus(context.taskId())).isEqualTo("QUEUED");
        assertThat(count("business.planning_task_event")).isEqualTo(1L);
    }

    @Test
    void serviceRejectsBypassEventWithUnknownRawField() throws Exception {
        PlanningContext context = createPlanningContext("review-bypass-unknown-field@example.com");
        // An unknown field in the raw snapshot also changes the fingerprint;
        // the gate rejects before state change.
        PlanningReviewRequiredEvent event = reviewEventWithoutParserValidationWithSnapshot(
                context, "review-v1-needs-repair-demo.json",
                node -> ((com.fasterxml.jackson.databind.node.ObjectNode)
                        node.at("/payload/itinerary")).put("bogusField", "x"));

        assertThatThrownBy(() -> reviewService.handle(event))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("does not match the report fingerprint");
        assertThat(taskStatus(context.taskId())).isEqualTo("QUEUED");
        assertThat(count("business.planning_task_event")).isEqualTo(1L);
    }

    private PlanningReviewRequiredEvent reviewEventWithoutParserValidation(
            PlanningContext context, String fixtureName,
            java.util.function.Consumer<com.fasterxml.jackson.databind.node.ObjectNode> mutate
    ) throws Exception {        String fixture = PlanningCompletedEventFixture.sharedReviewV1Fixture(fixtureName);
        com.fasterxml.jackson.databind.node.ObjectNode tree =
                (com.fasterxml.jackson.databind.node.ObjectNode) objectMapper.readTree(fixture);
        tree.put("eventId", UUID.randomUUID().toString())
                .put("traceId", context.traceId().toString())
                .put("taskId", context.taskId().toString())
                .put("tripId", context.tripId().toString())
                .put("runId", UUID.randomUUID().toString());
        mutate.accept(tree);
        // Bypass the parser entirely (parser-level rejection is covered
        // separately); deserialize straight into the event DTO.
        return objectMapper.treeToValue(tree, PlanningReviewRequiredEvent.class);
    }

    /**
     * Like {@link #reviewEventWithoutParserValidation} but attaches the raw
     * itinerary snapshot after the mutation, so the service integrity gate is
     * exercised with a present-but-possibly-inconsistent snapshot.
     */
    private PlanningReviewRequiredEvent reviewEventWithoutParserValidationWithSnapshot(
            PlanningContext context, String fixtureName,
            java.util.function.Consumer<com.fasterxml.jackson.databind.node.ObjectNode> mutate
    ) throws Exception {
        String fixture = PlanningCompletedEventFixture.sharedReviewV1Fixture(fixtureName);
        com.fasterxml.jackson.databind.node.ObjectNode tree =
                (com.fasterxml.jackson.databind.node.ObjectNode) objectMapper.readTree(fixture);
        tree.put("eventId", UUID.randomUUID().toString())
                .put("traceId", context.traceId().toString())
                .put("taskId", context.taskId().toString())
                .put("tripId", context.tripId().toString())
                .put("runId", UUID.randomUUID().toString());
        mutate.accept(tree);
        PlanningReviewRequiredEvent event =
                objectMapper.treeToValue(tree, PlanningReviewRequiredEvent.class);
        PlanningReviewRequiredEvent.Payload payload = event.payload();
        return new PlanningReviewRequiredEvent(
                event.eventType(), event.schemaVersion(), event.eventId(), event.traceId(),
                event.taskId(), event.tripId(), event.runId(), event.occurredAt(),
                new PlanningReviewRequiredEvent.Payload(
                        payload.status(), payload.provider(), payload.itinerary(),
                        payload.knowledge(), payload.factImpacts(),
                        payload.providerProvenance(), payload.feasibilityReport(),
                        tree.at("/payload/itinerary").deepCopy()
                )
        );
    }

    private long count(String table) {
        return jdbcTemplate.queryForObject(
                "SELECT count(*) FROM " + table, Long.class);
    }

    private long latestTaskEventId(UUID taskId) {
        return jdbcTemplate.queryForObject("""
                SELECT COALESCE(MAX(id), 0) FROM business.planning_task_event
                WHERE task_id = ?
                """, Long.class, taskId);
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

    // ── R4: SSE replay/live termination on WAITING_USER ──────────────────

    @Test
    void replaysReviewEventsAfterTheLastSeenEventAndClosesAWaitingUserStream() throws Exception {
        PlanningContext context = createPlanningContext("sse-review-replay@example.com");
        long queuedEventId = latestTaskEventId(context.taskId());
        reviewService.handle(reviewEvent(context, "review-v1-needs-repair-demo.json"));

        MvcResult stream = mockMvc.perform(get(
                        "/api/planning-tasks/{taskId}/events", context.taskId())
                        .header("Authorization", bearer(context.accessToken()))
                        .header("Last-Event-ID", queuedEventId)
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted())
                .andReturn();

        // A WAITING_USER stream must terminate; otherwise this times out.
        stream.getAsyncResult(10_000);

        MvcResult dispatched = mockMvc.perform(asyncDispatch(stream))
                .andExpect(status().isOk())
                .andReturn();
        String body = new String(
                dispatched.getResponse().getContentAsByteArray(), StandardCharsets.UTF_8);
        List<SseFrame> frames = parseSseFrames(body);
        assertThat(frames).hasSize(1);
        SseFrame reviewFrame = frames.get(0);
        assertThat(reviewFrame.event()).isEqualTo("PLANNING_REVIEW_REQUIRED");
        // Last-Event-ID excludes the QUEUED event: only the review event replays.
        assertThat(reviewFrame.id()).isGreaterThan(queuedEventId);

        // Deep-compare the replayed payload with the stored DB payload and
        // verify the event envelope comes from the stored record.
        Map<String, Object> stored = jdbcTemplate.queryForMap("""
                SELECT payload::text AS payload, id, event_id, task_id, event_type, schema_version
                FROM business.planning_task_event
                WHERE task_id = ? AND event_type = 'PLANNING_REVIEW_REQUIRED'
                ORDER BY id DESC LIMIT 1
                """, context.taskId());
        assertThat(reviewFrame.id()).isEqualTo(((Number) stored.get("id")).longValue());
        // TaskEventView.eventId is the stored DB row id (the SSE stream id).
        assertThat(reviewFrame.data().path("eventId").asLong())
                .isEqualTo(((Number) stored.get("id")).longValue());
        assertThat(reviewFrame.data().path("taskId").asText())
                .isEqualTo(stored.get("task_id").toString());
        assertThat(reviewFrame.data().path("eventType").asText())
                .isEqualTo(stored.get("event_type").toString());
        assertThat(reviewFrame.data().path("schemaVersion").asInt())
                .isEqualTo(((Number) stored.get("schema_version")).intValue());
        JsonNode dbPayload = objectMapper.readTree((String) stored.get("payload"));
        assertThat(reviewFrame.data().path("payload")).isEqualTo(dbPayload);
    }

    @Test
    void streamsAQueuedEventAndTheRealTimeReviewToAnExistingSubscriber() throws Exception {
        PlanningContext context = createPlanningContext("sse-review-live@example.com");

        MvcResult stream = mockMvc.perform(get(
                        "/api/planning-tasks/{taskId}/events", context.taskId())
                        .header("Authorization", bearer(context.accessToken()))
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted())
                .andReturn();

        reviewService.handle(reviewEvent(context, "review-v1-needs-repair-demo.json"));

        // A live PLANNING_REVIEW_REQUIRED publish must close the stream.
        stream.getAsyncResult(10_000);

        MvcResult dispatched = mockMvc.perform(asyncDispatch(stream))
                .andExpect(status().isOk())
                .andReturn();
        String body = new String(
                dispatched.getResponse().getContentAsByteArray(), StandardCharsets.UTF_8);
        List<SseFrame> frames = parseSseFrames(body);
        // QUEUED replay + live review event.
        assertThat(frames).hasSize(2);
        SseFrame reviewFrame = frames.stream()
                .filter(f -> "PLANNING_REVIEW_REQUIRED".equals(f.event()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("no review frame"));

        // Deep-compare the live payload with the stored DB payload; the event
        // id and envelope must come from the stored record.
        Map<String, Object> stored = jdbcTemplate.queryForMap("""
                SELECT payload::text AS payload, id, event_id
                FROM business.planning_task_event
                WHERE task_id = ? AND event_type = 'PLANNING_REVIEW_REQUIRED'
                ORDER BY id DESC LIMIT 1
                """, context.taskId());
        assertThat(reviewFrame.id()).isEqualTo(((Number) stored.get("id")).longValue());
        // TaskEventView.eventId is the stored DB row id (the SSE stream id).
        assertThat(reviewFrame.data().path("eventId").asLong())
                .isEqualTo(((Number) stored.get("id")).longValue());
        JsonNode dbPayload = objectMapper.readTree((String) stored.get("payload"));
        assertThat(reviewFrame.data().path("payload")).isEqualTo(dbPayload);

        // Payload semantics: report + candidate present, no evaluation.
        JsonNode payload = reviewFrame.data().path("payload");
        assertThat(payload.path("status").asText()).isEqualTo("WAITING_USER");
        assertThat(payload.path("feasibilityReport").path("status").asText())
                .isEqualTo("NEEDS_REPAIR");
        assertThat(payload.path("candidateItinerary").path("days")).hasSize(1);
        assertThat(payload.path("evaluation").isMissingNode()
                || payload.path("evaluation").isNull()).isTrue();
    }

    /**
     * Parses a raw SSE body into frames with id/event/data.  The data JSON is
     * deserialised so tests can deep-compare payloads instead of relying on
     * containsString field-name checks.
     */
    private List<SseFrame> parseSseFrames(String body) throws Exception {
        java.util.ArrayList<SseFrame> frames = new java.util.ArrayList<>();
        String currentId = null;
        String currentEvent = null;
        StringBuilder data = new StringBuilder();
        for (String line : body.split("\\R")) {
            if (line.startsWith("id:")) {
                currentId = line.substring(3).trim();
            } else if (line.startsWith("event:")) {
                currentEvent = line.substring(6).trim();
            } else if (line.startsWith("data:")) {
                if (data.length() > 0) {
                    data.append('\n');
                }
                data.append(line.substring(5).trim());
            } else if (line.isEmpty() && currentEvent != null) {
                frames.add(new SseFrame(
                        currentId == null ? 0L : Long.parseLong(currentId),
                        currentEvent,
                        objectMapper.readTree(data.toString())));
                currentId = null;
                currentEvent = null;
                data.setLength(0);
            }
        }
        if (currentEvent != null) {
            frames.add(new SseFrame(
                    currentId == null ? 0L : Long.parseLong(currentId),
                    currentEvent,
                    objectMapper.readTree(data.toString())));
        }
        return frames;
    }

    private record SseFrame(long id, String event, JsonNode data) {
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

    // ── B12: late progress after WAITING_USER is idempotently ignored ──────

    @Autowired
    private PlanningProgressService progressService;

    @Autowired
    private PlanningProgressEventParser progressEventParser;

    @Test
    void lateProgressAfterReviewIsIgnoredWithoutTouchingTheTerminalState() throws Exception {
        PlanningContext context = createPlanningContext("review-late-progress@example.com");
        reviewService.handle(reviewEvent(context, "review-v1-needs-repair-demo.json"));
        assertThat(taskStatus(context.taskId())).isEqualTo("WAITING_USER");

        // The review outcome reached the server first; the worker's progress
        // route arrives afterwards.  It must be a silent no-op: no exception,
        // no state change, no extra event rows, no DLQ-inducing rejection.
        progressService.handle(progressEvent(
                UUID.randomUUID(), context, "RESULT_PUBLISHING", 10
        ));

        assertThat(taskStatus(context.taskId())).isEqualTo("WAITING_USER");
        assertThat(jdbcTemplate.queryForObject("""
                SELECT COUNT(*) FROM business.planning_task_event
                WHERE task_id = ? AND event_type = 'PLANNING_PROGRESS'
                """, Integer.class, context.taskId())).isZero();
        assertThat(jdbcTemplate.queryForObject("""
                SELECT COUNT(*) FROM business.planning_task_event
                WHERE task_id = ? AND event_type = 'PLANNING_REVIEW_REQUIRED'
                """, Integer.class, context.taskId())).isEqualTo(1);
    }

    private io.github.tobehardoo.trippilot.infrastructure.mq.PlanningProgressEvent progressEvent(
            UUID eventId,
            PlanningContext context,
            String stage,
            int sequence
    ) {
        String body = """
                {
                  "eventType":"PLANNING_PROGRESS",
                  "schemaVersion":1,
                  "eventId":"%s",
                  "traceId":"%s",
                  "taskId":"%s",
                  "tripId":"%s",
                  "occurredAt":"2026-07-27T08:00:00Z",
                  "payload":{
                    "stage":"%s",
                    "sequence":%d,
                    "progress":%d,
                    "message":"Planning progress update",
                    "statistics":{"tripDays":1}
                  }
                }
                """.formatted(
                eventId, context.traceId(), context.taskId(), context.tripId(),
                stage, sequence, sequence * 10
        );
        return progressEventParser.parse(body.getBytes(StandardCharsets.UTF_8));
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
