package io.github.tobehardoo.trippilot.planning;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.messaging.PlanningCompletedEvent;
import io.github.tobehardoo.trippilot.messaging.PlanningCompletedEventParser;
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
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class PlanningCompletionFlowIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private PlanningCompletedEventParser eventParser;

    @Autowired
    private PlanningCompletionService completionService;

    @Test
    void persistsACompletedTaskAsAnImmutableRelationalItineraryVersion() throws Exception {
        PlanningContext context = createPlanningContext("completion-owner@example.com");

        completionService.handle(completedEvent(UUID.randomUUID(), context));

        Map<String, Object> result = jdbcTemplate.queryForMap("""
                SELECT planning_task.status,
                       itinerary.current_version_id,
                       itinerary_version.id AS version_id,
                       itinerary_version.version_number,
                       itinerary_version.planning_task_id,
                       itinerary_version.title,
                       itinerary_version.estimated_total_cost,
                       itinerary_version.constraint_snapshot ->> 'travelers' AS travelers
                FROM business.planning_task
                JOIN business.itinerary ON itinerary.trip_id = planning_task.trip_id
                JOIN business.itinerary_version
                  ON itinerary_version.id = itinerary.current_version_id
                WHERE planning_task.id = ?
                """, context.taskId());

        assertThat(result).containsEntry("status", "SUCCEEDED")
                .containsEntry("version_number", 1)
                .containsEntry("planning_task_id", context.taskId())
                .containsEntry("title", "广州 Demo 行程")
                .containsEntry("travelers", "2");
        assertThat(result.get("current_version_id")).isEqualTo(result.get("version_id"));
        assertThat(count("business.planning_task_event")).isEqualTo(2);
        assertThat(count("business.itinerary")).isEqualTo(1);
        assertThat(count("business.itinerary_version")).isEqualTo(1);
        assertThat(count("business.itinerary_day")).isEqualTo(1);
        assertThat(count("business.activity")).isEqualTo(1);

        mockMvc.perform(get("/api/trips/{tripId}/itinerary", context.tripId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.versionNumber").value(1))
                .andExpect(jsonPath("$.title").value("广州 Demo 行程"))
                .andExpect(jsonPath("$.days[0].date").value("2026-08-01"))
                .andExpect(jsonPath("$.days[0].activities[0].source").value("DEMO"));
    }

    @Test
    void persistsAndReturnsV2AmapActivityMetadata() throws Exception {
        PlanningContext context = createPlanningContext("completion-amap@example.com");
        PlanningCompletedEvent event = eventParser.parse(bytes(
                PlanningCompletedEventFixture.completedAmapEventV2(
                        UUID.randomUUID(), context.traceId(), context.taskId(), context.tripId()
                )
        ));

        completionService.handle(event);

        Map<String, Object> activity = jdbcTemplate.queryForMap("""
                SELECT itinerary_version.provider, activity.source, activity.provider_poi_id,
                       activity.longitude, activity.latitude, activity.address
                FROM business.itinerary
                JOIN business.itinerary_version
                  ON itinerary_version.id = itinerary.current_version_id
                JOIN business.itinerary_day
                  ON itinerary_day.itinerary_version_id = itinerary_version.id
                JOIN business.activity ON activity.itinerary_day_id = itinerary_day.id
                WHERE itinerary.trip_id = ?
                """, context.tripId());

        assertThat(activity).containsEntry("provider", "AMAP")
                .containsEntry("source", "AMAP")
                .containsEntry("provider_poi_id", "B00140TWHT")
                .containsEntry("address", "珠江东路2号");
        assertThat((BigDecimal) activity.get("longitude"))
                .isEqualByComparingTo("113.3192630");
        assertThat((BigDecimal) activity.get("latitude"))
                .isEqualByComparingTo("23.1090780");

        mockMvc.perform(get("/api/trips/{tripId}/itinerary", context.tripId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.provider").value("AMAP"))
                .andExpect(jsonPath("$.days[0].activities[0].source").value("AMAP"))
                .andExpect(jsonPath("$.days[0].activities[0].providerPoiId")
                        .value("B00140TWHT"))
                .andExpect(jsonPath("$.days[0].activities[0].coordinates.longitude")
                        .value(113.319263))
                .andExpect(jsonPath("$.days[0].activities[0].coordinates.latitude")
                        .value(23.109078))
                .andExpect(jsonPath("$.days[0].activities[0].address")
                        .value("珠江东路2号"));
    }

    @Test
    void handlesTheSameCompletedEventMoreThanOnceWithoutDuplicatingBusinessEffects() throws Exception {
        PlanningContext context = createPlanningContext("completion-repeat@example.com");
        PlanningCompletedEvent event = completedEvent(UUID.randomUUID(), context);

        completionService.handle(event);
        completionService.handle(event);

        assertThat(count("business.planning_task_event")).isEqualTo(2);
        assertThat(count("business.itinerary")).isEqualTo(1);
        assertThat(count("business.itinerary_version")).isEqualTo(1);
        assertThat(count("business.itinerary_day")).isEqualTo(1);
        assertThat(count("business.activity")).isEqualTo(1);
    }

    @Test
    void rejectsAnEventIdThatAlreadyBelongsToAnotherPlanningTask() throws Exception {
        PlanningContext first = createPlanningContext("event-id-first@example.com");
        PlanningContext second = createPlanningContext("event-id-second@example.com");
        UUID reusedEventId = UUID.randomUUID();
        completionService.handle(completedEvent(reusedEventId, first));

        assertThatThrownBy(() -> completionService.handle(completedEvent(reusedEventId, second)))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("already belongs to another planning task");

        assertThat(taskStatus(second.taskId())).isEqualTo("QUEUED");
        assertThat(count("business.planning_task_event")).isEqualTo(3);
        assertThat(count("business.itinerary_version")).isEqualTo(1);
    }

    @Test
    void rejectsACompletedEventWhoseTaskIdentityDoesNotMatch() throws Exception {
        PlanningContext context = createPlanningContext("completion-mismatch@example.com");
        PlanningCompletedEvent mismatched = eventParser.parse(bytes(
                PlanningCompletedEventFixture.completedEvent(
                        UUID.randomUUID(), context.traceId(), context.taskId(), UUID.randomUUID()
                )
        ));

        assertThatThrownBy(() -> completionService.handle(mismatched))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("does not match its planning task");

        assertThat(taskStatus(context.taskId())).isEqualTo("QUEUED");
        assertThat(count("business.planning_task_event")).isEqualTo(1);
        assertThat(count("business.itinerary_version")).isZero();
    }

    @Test
    void marksAStaleCompletedResultFailedWithoutCreatingAnItinerary() throws Exception {
        PlanningContext context = createPlanningContext("completion-stale@example.com");
        updateConstraints(context.accessToken(), context.tripId(), 3);
        UUID eventId = UUID.randomUUID();

        completionService.handle(completedEvent(eventId, context));
        completionService.handle(completedEvent(eventId, context));

        Map<String, Object> taskEvent = jdbcTemplate.queryForMap("""
                SELECT event_type, payload ->> 'status' AS status,
                       payload ->> 'errorCode' AS error_code
                FROM business.planning_task_event
                WHERE event_id = ?
                """, eventId);
        assertThat(taskStatus(context.taskId())).isEqualTo("FAILED");
        assertThat(taskEvent).containsEntry("event_type", "PLANNING_FAILED")
                .containsEntry("status", "FAILED")
                .containsEntry("error_code", "STALE_TRIP_VERSION");
        assertThat(count("business.planning_task_event")).isEqualTo(2);
        assertThat(count("business.itinerary")).isZero();
        assertThat(count("business.itinerary_version")).isZero();
    }

    @Test
    void rollsBackEveryCompletionWriteWhenAnActivityCannotBePersisted() throws Exception {
        PlanningContext context = createPlanningContext("completion-rollback@example.com");
        jdbcTemplate.execute("""
                CREATE FUNCTION business.fail_activity_insert() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'forced activity failure';
                END;
                $$ LANGUAGE plpgsql
                """);
        jdbcTemplate.execute("""
                CREATE TRIGGER fail_activity_insert
                BEFORE INSERT ON business.activity
                FOR EACH ROW EXECUTE FUNCTION business.fail_activity_insert()
                """);

        try {
            assertThatThrownBy(() -> completionService.handle(completedEvent(UUID.randomUUID(), context)))
                    .rootCause()
                    .hasMessageContaining("forced activity failure");
        } finally {
            jdbcTemplate.execute("DROP TRIGGER fail_activity_insert ON business.activity");
            jdbcTemplate.execute("DROP FUNCTION business.fail_activity_insert()");
        }

        assertThat(taskStatus(context.taskId())).isEqualTo("QUEUED");
        assertThat(count("business.planning_task_event")).isEqualTo(1);
        assertThat(count("business.itinerary")).isZero();
        assertThat(count("business.itinerary_version")).isZero();
        assertThat(count("business.itinerary_day")).isZero();
        assertThat(count("business.activity")).isZero();
    }

    @Test
    void hidesTheCurrentItineraryFromAnotherUser() throws Exception {
        PlanningContext context = createPlanningContext("itinerary-private-owner@example.com");
        completionService.handle(completedEvent(UUID.randomUUID(), context));
        String otherToken = registerAndGetAccessToken("itinerary-private-other@example.com");

        mockMvc.perform(get("/api/trips/{tripId}/itinerary", context.tripId())
                        .header("Authorization", bearer(otherToken)))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("ITINERARY_NOT_FOUND"));
    }

    @Test
    void returnsNotFoundBeforeTheOwnedTripHasAnItinerary() throws Exception {
        String accessToken = registerAndGetAccessToken("itinerary-empty-owner@example.com");
        UUID tripId = createTrip(accessToken);

        mockMvc.perform(get("/api/trips/{tripId}/itinerary", tripId)
                        .header("Authorization", bearer(accessToken)))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("ITINERARY_NOT_FOUND"));
    }

    @Test
    void replaysOnlyTaskEventsAfterTheLastSeenEventAndClosesATerminalStream() throws Exception {
        PlanningContext context = createPlanningContext("sse-replay@example.com");
        long queuedEventId = latestTaskEventId(context.taskId());
        completionService.handle(completedEvent(UUID.randomUUID(), context));

        MvcResult stream = mockMvc.perform(get("/api/planning-tasks/{taskId}/events", context.taskId())
                        .header("Authorization", bearer(context.accessToken()))
                        .header("Last-Event-ID", queuedEventId)
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted())
                .andReturn();

        mockMvc.perform(asyncDispatch(stream))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("event:PLANNING_COMPLETED")))
                .andExpect(content().string(not(containsString("event:PLANNING_QUEUED"))));
    }

    @Test
    void streamsAQueuedEventAndTheRealTimeCompletionToAnExistingSubscriber() throws Exception {
        PlanningContext context = createPlanningContext("sse-live@example.com");

        MvcResult stream = mockMvc.perform(get("/api/planning-tasks/{taskId}/events", context.taskId())
                        .header("Authorization", bearer(context.accessToken()))
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted())
                .andReturn();

        completionService.handle(completedEvent(UUID.randomUUID(), context));

        mockMvc.perform(asyncDispatch(stream))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("event:PLANNING_QUEUED")))
                .andExpect(content().string(containsString("event:PLANNING_COMPLETED")));
    }

    @Test
    void hidesTheTaskEventStreamFromAnotherUser() throws Exception {
        PlanningContext context = createPlanningContext("sse-private-owner@example.com");
        String otherToken = registerAndGetAccessToken("sse-private-other@example.com");

        mockMvc.perform(get("/api/planning-tasks/{taskId}/events", context.taskId())
                        .header("Authorization", bearer(otherToken))
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(status().isNotFound());
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

    private PlanningCompletedEvent completedEvent(UUID eventId, PlanningContext context) {
        return eventParser.parse(bytes(PlanningCompletedEventFixture.completedEvent(
                eventId, context.traceId(), context.taskId(), context.tripId()
        )));
    }

    private String taskStatus(UUID taskId) {
        return jdbcTemplate.queryForObject(
                "SELECT status FROM business.planning_task WHERE id = ?", String.class, taskId
        );
    }

    private long latestTaskEventId(UUID taskId) {
        Long id = jdbcTemplate.queryForObject(
                "SELECT max(id) FROM business.planning_task_event WHERE task_id = ?", Long.class, taskId
        );
        if (id == null) {
            throw new IllegalStateException("Planning task has no events");
        }
        return id;
    }

    private int count(String table) {
        Integer count = jdbcTemplate.queryForObject("SELECT count(*) FROM " + table, Integer.class);
        return count == null ? 0 : count;
    }

    private JsonNode json(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsByteArray());
    }

    private byte[] bytes(String value) {
        return value.getBytes(StandardCharsets.UTF_8);
    }

    private String bearer(String accessToken) {
        return "Bearer " + accessToken;
    }

    private record PlanningContext(
            String accessToken,
            UUID tripId,
            UUID taskId,
            UUID traceId
    ) {
    }
}
