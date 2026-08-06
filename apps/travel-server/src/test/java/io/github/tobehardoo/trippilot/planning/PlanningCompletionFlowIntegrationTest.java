package io.github.tobehardoo.trippilot.planning;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEventParser;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningFailedEventParser;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningFailedEventParserTest;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningProgressEvent;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningProgressEventParser;
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

    @Autowired
    private PlanningFailedEventParser failedEventParser;

    @Autowired
    private PlanningFailureService failureService;

    @Autowired
    private PlanningProgressEventParser progressEventParser;

    @Autowired
    private PlanningProgressService progressService;

    @Test
    void persistsMonotonicProgressEventsAndMarksTheTaskRunning() throws Exception {
        PlanningContext context = createPlanningContext("planning-progress@example.com");
        PlanningProgressEvent accepted = progressEvent(
                UUID.randomUUID(), context, "TASK_ACCEPTED", 1
        );
        PlanningProgressEvent validating = progressEvent(
                UUID.randomUUID(), context, "CONTEXT_VALIDATING", 2
        );

        progressService.handle(accepted);
        progressService.handle(accepted);
        progressService.handle(validating);

        Map<String, Object> result = jdbcTemplate.queryForMap("""
                SELECT planning_task.status,
                       COUNT(planning_task_event.id) FILTER (
                           WHERE planning_task_event.event_type = 'PLANNING_PROGRESS'
                       ) AS progress_count,
                       MAX((planning_task_event.payload ->> 'sequence')::integer) AS latest_sequence
                FROM business.planning_task
                LEFT JOIN business.planning_task_event
                  ON planning_task_event.task_id = planning_task.id
                WHERE planning_task.id = ?
                GROUP BY planning_task.status
                """, context.taskId());

        assertThat(result).containsEntry("status", "RUNNING")
                .containsEntry("progress_count", 2L)
                .containsEntry("latest_sequence", 2);
        assertThatThrownBy(() -> progressService.handle(progressEvent(
                UUID.randomUUID(), context, "CITY_FACTS_LOADING", 2
        ))).isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("sequence must increase");
    }

    @Test
    void ignoresLateProgressAfterCompletionBecauseBrokerRoutesCanArriveOutOfOrder() throws Exception {
        PlanningContext context = createPlanningContext("late-progress@example.com");
        completionService.handle(completedEvent(UUID.randomUUID(), context));

        progressService.handle(progressEvent(
                UUID.randomUUID(), context, "RESULT_PUBLISHING", 10
        ));

        assertThat(jdbcTemplate.queryForObject("""
                SELECT status FROM business.planning_task WHERE id = ?
                """, String.class, context.taskId())).isEqualTo("SUCCEEDED");
        assertThat(jdbcTemplate.queryForObject("""
                SELECT COUNT(*) FROM business.planning_task_event
                WHERE task_id = ? AND event_type = 'PLANNING_PROGRESS'
                """, Integer.class, context.taskId())).isZero();
    }

    @Test
    void persistsAnActionableInfeasibilityFailureIdempotently() throws Exception {
        PlanningContext context = createPlanningContext("planning-infeasible@example.com");
        UUID eventId = UUID.randomUUID();
        String body = PlanningFailedEventParserTest.json(eventId)
                .replace("8f5ef9c2-c194-4292-b847-5b9dcfda978b", context.traceId().toString())
                .replace("b0642d34-e24f-4b24-9ea7-82a68a4be781", context.taskId().toString())
                .replace("08be9aca-fb30-4309-aa4b-93c240f19d75", context.tripId().toString());

        var event = failedEventParser.parse(body.getBytes(StandardCharsets.UTF_8));
        failureService.handle(event);
        failureService.handle(event);

        Map<String, Object> stored = jdbcTemplate.queryForMap("""
                SELECT planning_task.status, planning_task.error_code,
                       planning_task_event.event_type,
                       planning_task_event.payload -> 'conflicts' -> 0 ->> 'code' AS conflict_code
                FROM business.planning_task
                JOIN business.planning_task_event
                  ON planning_task_event.task_id = planning_task.id
                 AND planning_task_event.event_id = ?
                WHERE planning_task.id = ?
                """, eventId, context.taskId());

        assertThat(stored).containsEntry("status", "FAILED")
                .containsEntry("error_code", "NO_FEASIBLE_ITINERARY")
                .containsEntry("event_type", "PLANNING_FAILED")
                .containsEntry("conflict_code", "INSUFFICIENT_DAY_CAPACITY");
        assertThat(count("business.itinerary_version")).isZero();
    }

    @Test
    void persistsProviderFailureV2AndExposesSafeMetadataWithoutCreatingVersions()
            throws Exception {
        PlanningContext context = createPlanningContext("planning-provider-failure@example.com");
        UUID eventId = UUID.randomUUID();
        var event = failedEventParser.parse(bytes(providerFailureV2(eventId, context)));

        failureService.handle(event);
        failureService.handle(event);

        Map<String, Object> stored = jdbcTemplate.queryForMap("""
                SELECT planning_task.status, planning_task.error_code,
                       planning_task.error_message,
                       planning_task_event.schema_version,
                       planning_task_event.payload ->> 'errorCategory' AS error_category,
                       planning_task_event.payload ->> 'safeProviderCode' AS provider_code,
                       planning_task_event.payload ->> 'retryCount' AS retry_count
                FROM business.planning_task
                JOIN business.planning_task_event
                  ON planning_task_event.task_id = planning_task.id
                 AND planning_task_event.event_id = ?
                WHERE planning_task.id = ?
                """, eventId, context.taskId());

        assertThat(stored).containsEntry("status", "FAILED")
                .containsEntry("error_code", "PROVIDER_AUTHENTICATION_FAILED")
                .containsEntry("error_message", "AMap authentication failed")
                .containsEntry("schema_version", 2)
                .containsEntry("error_category", "AUTHENTICATION_ERROR")
                .containsEntry("provider_code", "10001")
                .containsEntry("retry_count", "0");
        assertThat(count("business.itinerary_version")).isZero();
        assertThat(count("business.activity")).isZero();
        assertThat(count("business.transit_leg")).isZero();

        mockMvc.perform(get("/api/planning-tasks/{taskId}", context.taskId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("FAILED"))
                .andExpect(jsonPath("$.errorCode")
                        .value("PROVIDER_AUTHENTICATION_FAILED"))
                .andExpect(jsonPath("$.errorCategory").value("AUTHENTICATION_ERROR"))
                .andExpect(jsonPath("$.provider").value("AMAP"))
                .andExpect(jsonPath("$.operation").value("POI_SEARCH"))
                .andExpect(jsonPath("$.retryable").value(false))
                .andExpect(jsonPath("$.retryCount").value(0))
                .andExpect(jsonPath("$.fallbackAttempted").value(false))
                .andExpect(jsonPath("$.fallbackSucceeded").value(false))
                .andExpect(jsonPath("$.safeMessage").value("AMap authentication failed"))
                .andExpect(jsonPath("$.safeProviderCode").value("10001"))
                .andExpect(jsonPath("$.evaluation").doesNotExist());
    }

    @Test
    void returnsEvaluationThroughTaskApiAndLastEventIdReplay() throws Exception {
        PlanningContext context = createPlanningContext("completion-evaluation@example.com");
        long queuedEventId = latestTaskEventId(context.taskId());
        completionService.handle(sharedV6Event(
                "completion-v6-evaluation-clean.json", UUID.randomUUID(), context));

        mockMvc.perform(get("/api/planning-tasks/{taskId}", context.taskId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("SUCCEEDED"))
                .andExpect(jsonPath("$.evaluation.schemaVersion").value(1))
                .andExpect(jsonPath("$.evaluation.evaluatorVersion").value("rule-v1"))
                .andExpect(jsonPath("$.evaluation.overallScore").value(97))
                .andExpect(jsonPath("$.evaluation.dimensions.interestMatch").value(80));

        MvcResult stream = mockMvc.perform(get(
                        "/api/planning-tasks/{taskId}/events", context.taskId())
                        .header("Authorization", bearer(context.accessToken()))
                        .header("Last-Event-ID", queuedEventId)
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted())
                .andReturn();
        mockMvc.perform(asyncDispatch(stream))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("event:PLANNING_COMPLETED")))
                .andExpect(content().string(containsString("\"evaluation\":{")))
                .andExpect(content().string(containsString("\"overallScore\":97")));
    }

    @Test
    void remapsMixedEvaluationEntityIdsToPersistedTransitIdentity() throws Exception {
        PlanningContext context = createPlanningContext("completion-evaluation-mixed@example.com");
        completionService.handle(sharedV6Event(
                "completion-v6-evaluation-mixed-provider.json",
                UUID.randomUUID(),
                context
        ));
        UUID persistedTransitId = jdbcTemplate.queryForObject(
                "SELECT id FROM business.transit_leg", UUID.class);

        mockMvc.perform(get("/api/planning-tasks/{taskId}", context.taskId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.evaluation.overallScore").value(94))
                .andExpect(jsonPath("$.fallbackOperations[0].transitId")
                        .value(persistedTransitId.toString()))
                .andExpect(jsonPath("$.evaluation.warnings[0].entityId")
                        .value(persistedTransitId.toString()))
                .andExpect(jsonPath("$.evaluation.warnings[1].entityId")
                        .value(persistedTransitId.toString()))
                .andExpect(jsonPath("$.evaluation.decisions[0].subjectId")
                        .value(persistedTransitId.toString()));
    }

    @Test
    void remapsEvaluationActivityIdWhenTheDayHasNoTransitLeg() throws Exception {
        PlanningContext context = createPlanningContext(
                "completion-evaluation-single-activity@example.com");
        ObjectNode fixture = sharedV6Fixture(
                "completion-v6-evaluation-fixed-appointment.json",
                UUID.randomUUID(), context);
        ArrayNode activities = (ArrayNode) fixture.at(
                "/payload/itinerary/days/0/activities");
        activities.remove(1);
        ((ObjectNode) fixture.at("/payload/itinerary/days/0"))
                .put("date", "2026-08-01");
        ((ObjectNode) activities.get(0))
                .put("startTime", "2026-08-01T09:00:00+08:00")
                .put("endTime", "2026-08-01T11:00:00+08:00");
        ((ArrayNode) fixture.at(
                "/payload/itinerary/days/0/transitLegs")).removeAll();

        completionService.handle(eventParser.parse(bytes(
                objectMapper.writeValueAsString(fixture))));

        UUID persistedActivityId = jdbcTemplate.queryForObject(
                "SELECT id FROM business.activity", UUID.class);
        mockMvc.perform(get("/api/planning-tasks/{taskId}", context.taskId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.evaluation.decisions[1].subjectId")
                        .value(persistedActivityId.toString()));
    }

    @Test
    void keepsLegacyCompletionEvaluationNullInTaskApi() throws Exception {
        PlanningContext context = createPlanningContext("completion-evaluation-legacy@example.com");
        completionService.handle(sharedV6Event(
                "completion-v6-legacy-without-evaluation.json",
                UUID.randomUUID(),
                context
        ));

        mockMvc.perform(get("/api/planning-tasks/{taskId}", context.taskId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("SUCCEEDED"))
                .andExpect(jsonPath("$.evaluation").doesNotExist());
    }

    @Test
    void ignoresEquivalentV2FailureAfterV1AlreadyMadeTheTaskTerminal() throws Exception {
        PlanningContext context = createPlanningContext("planning-failure-version-race@example.com");
        UUID v1EventId = UUID.randomUUID();
        String v1Body = PlanningFailedEventParserTest.json(v1EventId)
                .replace("8f5ef9c2-c194-4292-b847-5b9dcfda978b", context.traceId().toString())
                .replace("b0642d34-e24f-4b24-9ea7-82a68a4be781", context.taskId().toString())
                .replace("08be9aca-fb30-4309-aa4b-93c240f19d75", context.tripId().toString());
        failureService.handle(failedEventParser.parse(bytes(v1Body)));

        String v2Body = providerFailureV2(UUID.randomUUID(), context)
                .replace("PROVIDER_AUTHENTICATION_FAILED", "NO_FEASIBLE_ITINERARY")
                .replace("AUTHENTICATION_ERROR", "PLANNING_INFEASIBLE")
                .replace("\"provider\": \"AMAP\"", "\"provider\": \"PLANNER\"")
                .replace("\"operation\": \"POI_SEARCH\"", "\"operation\": \"PLANNING\"")
                .replace("\"safeProviderCode\": \"10001\",", "")
                .replace("\"conflicts\": []", "\"conflicts\": [{\"code\":\"INSUFFICIENT_DAY_CAPACITY\",\"message\":\"No capacity\",\"affected\":[\"day\"]}]");
        failureService.handle(failedEventParser.parse(bytes(v2Body)));

        assertThat(taskStatus(context.taskId())).isEqualTo("FAILED");
        assertThat(jdbcTemplate.queryForObject("""
                SELECT count(*) FROM business.planning_task_event
                WHERE task_id = ? AND event_type = 'PLANNING_FAILED'
                """, Integer.class, context.taskId())).isEqualTo(1);
    }

    @Test
    void rejectsLateFailureWithoutOverwritingASuccessfulTask() throws Exception {
        PlanningContext context = createPlanningContext("planning-late-failure@example.com");
        completionService.handle(completedEvent(UUID.randomUUID(), context));
        var lateFailure = failedEventParser.parse(bytes(
                providerFailureV2(UUID.randomUUID(), context)
        ));

        assertThatThrownBy(() -> failureService.handle(lateFailure))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("status SUCCEEDED");
        assertThat(taskStatus(context.taskId())).isEqualTo("SUCCEEDED");
        assertThat(count("business.itinerary_version")).isEqualTo(1);
    }

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
    void persistsV8ScheduleFieldsIncludingStructuralMealWithoutMetadata() throws Exception {
        PlanningContext context = createPlanningContext("completion-v8@example.com");
        PlanningCompletedEvent event = eventParser.parse(bytes(
                PlanningCompletedEventFixture.completedAmapEventV8(
                        UUID.randomUUID(), context.traceId(), context.taskId(), context.tripId()
                )
        ));

        completionService.handle(event);

        Map<String, Object> day = jdbcTemplate.queryForMap("""
                SELECT itinerary_day.day_type
                FROM business.itinerary
                JOIN business.itinerary_version
                  ON itinerary_version.id = itinerary.current_version_id
                JOIN business.itinerary_day
                  ON itinerary_day.itinerary_version_id = itinerary_version.id
                WHERE itinerary.trip_id = ?
                """, context.tripId());
        assertThat(day).containsEntry("day_type", "ARRIVAL_DAY");

        List<Map<String, Object>> activities = jdbcTemplate.queryForList("""
                SELECT activity.title, activity.kind, activity.time_fixed,
                       activity.provider_poi_id
                FROM business.itinerary
                JOIN business.itinerary_version
                  ON itinerary_version.id = itinerary.current_version_id
                JOIN business.itinerary_day
                  ON itinerary_day.itinerary_version_id = itinerary_version.id
                JOIN business.activity ON activity.itinerary_day_id = itinerary_day.id
                WHERE itinerary.trip_id = ?
                ORDER BY activity.activity_order
                """, context.tripId());
        assertThat(activities.get(0))
                .containsEntry("kind", "ARRIVAL")
                .containsEntry("time_fixed", true)
                .containsEntry("provider_poi_id", "STATION-1");
        assertThat(activities.get(2))
                .containsEntry("kind", "MEAL")
                .containsEntry("time_fixed", false)
                .containsEntry("provider_poi_id", null);

        mockMvc.perform(get("/api/trips/{tripId}/itinerary", context.tripId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.days[0].dayType").value("ARRIVAL_DAY"))
                .andExpect(jsonPath("$.days[0].activities[0].kind").value("ARRIVAL"))
                .andExpect(jsonPath("$.days[0].activities[0].timeFixed").value(true))
                .andExpect(jsonPath("$.days[0].activities[2].kind").value("MEAL"))
                .andExpect(jsonPath("$.days[0].activities[2].timeFixed").value(false))
                .andExpect(jsonPath("$.days[0].activities[2].providerPoiId").doesNotExist());
    }

    @Test
    void persistsAndReturnsV3TransitLegsLinkedToAdjacentActivities() throws Exception {
        PlanningContext context = createPlanningContext("completion-route@example.com");
        PlanningCompletedEvent event = eventParser.parse(bytes(
                PlanningCompletedEventFixture.completedAmapEventV3(
                        UUID.randomUUID(), context.traceId(), context.taskId(), context.tripId()
                )
        ));

        completionService.handle(event);

        Map<String, Object> leg = jdbcTemplate.queryForMap("""
                SELECT transit_leg.mode, transit_leg.distance_meters,
                       transit_leg.duration_seconds, transit_leg.provider,
                       transit_leg.estimated, transit_leg.polyline::text AS polyline,
                       origin.title AS origin_title, destination.title AS destination_title
                FROM business.transit_leg
                JOIN business.activity AS origin ON origin.id = transit_leg.from_activity_id
                JOIN business.activity AS destination ON destination.id = transit_leg.to_activity_id
                """);
        assertThat(leg).containsEntry("mode", "WALKING")
                .containsEntry("distance_meters", 1280)
                .containsEntry("duration_seconds", 960)
                .containsEntry("provider", "AMAP")
                .containsEntry("estimated", false)
                .containsEntry("origin_title", "广东省博物馆")
                .containsEntry("destination_title", "广州塔");
        assertThat((String) leg.get("polyline")).contains("113.319263", "23.106414");

        mockMvc.perform(get("/api/trips/{tripId}/itinerary", context.tripId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.days[0].activities.length()").value(2))
                .andExpect(jsonPath("$.days[0].transitLegs.length()").value(1))
                .andExpect(jsonPath("$.days[0].transitLegs[0].fromActivityId").isNotEmpty())
                .andExpect(jsonPath("$.days[0].transitLegs[0].toActivityId").isNotEmpty())
                .andExpect(jsonPath("$.days[0].transitLegs[0].mode").value("WALKING"))
                .andExpect(jsonPath("$.days[0].transitLegs[0].distanceMeters").value(1280))
                .andExpect(jsonPath("$.days[0].transitLegs[0].durationSeconds").value(960))
                .andExpect(jsonPath("$.days[0].transitLegs[0].provider").value("AMAP"))
                .andExpect(jsonPath("$.days[0].transitLegs[0].estimated").value(false))
                .andExpect(jsonPath("$.days[0].transitLegs[0].polyline.length()").value(2));
    }

    @Test
    void persistsExplicitMixedProviderEvidenceWithStableTransitIdentity() throws Exception {
        PlanningContext context = createPlanningContext("completion-mixed-provider@example.com");
        UUID eventId = UUID.randomUUID();
        long queuedEventId = latestTaskEventId(context.taskId());
        PlanningCompletedEvent event = sharedV6Event(
                "completion-v6-multi-transit-mixed.json", eventId, context);

        completionService.handle(event);
        completionService.handle(event);

        Map<String, Object> taskEvent = jdbcTemplate.queryForMap("""
                SELECT payload ->> 'provider' AS provider,
                       payload ->> 'requestedProviderMode' AS requested_mode,
                       payload ->> 'fallbackSucceeded' AS fallback_succeeded,
                       payload -> 'actualProviders' AS actual_providers,
                       payload #>> '{fallbackOperations,0,operation}' AS operation,
                       payload #>> '{fallbackOperations,0,errorCategory}' AS error_category,
                       payload #>> '{fallbackOperations,0,errorCode}' AS error_code,
                       payload #>> '{fallbackOperations,0,retryCount}' AS retry_count,
                       payload #>> '{fallbackOperations,0,transitId}' AS transit_id,
                       payload #>> '{fallbackOperations,0,fromActivityId}' AS from_activity_id,
                       payload #>> '{fallbackOperations,0,toActivityId}' AS to_activity_id
                 FROM business.planning_task_event
                 WHERE event_id = ?
                 """, eventId);
        assertThat(taskEvent).containsEntry("provider", "MIXED")
                .containsEntry("requested_mode", "REAL_WITH_EXPLICIT_FALLBACK")
                .containsEntry("fallback_succeeded", "true")
                .containsEntry("operation", "ROUTE")
                .containsEntry("error_category", "TIMEOUT")
                .containsEntry("error_code", "PROVIDER_TIMEOUT")
                .containsEntry("retry_count", "2");
        assertThat(taskEvent.get("actual_providers").toString())
                .contains("AMAP", "DEMO");
        assertThat(count("business.itinerary_version")).isEqualTo(1);

        List<Map<String, Object>> legs = jdbcTemplate.queryForList("""
                SELECT transit_leg.id, transit_leg.leg_order, transit_leg.provider,
                       transit_leg.estimated, transit_leg.mode, transit_leg.locked,
                       transit_leg.polyline::text AS polyline,
                       origin.id AS origin_id, origin.title AS origin_title,
                       destination.id AS destination_id,
                       destination.title AS destination_title,
                       itinerary_version.provider AS version_provider
                FROM business.transit_leg
                JOIN business.activity AS origin
                  ON origin.id = transit_leg.from_activity_id
                JOIN business.activity AS destination
                  ON destination.id = transit_leg.to_activity_id
                JOIN business.itinerary_day
                  ON itinerary_day.id = transit_leg.itinerary_day_id
                JOIN business.itinerary_version
                  ON itinerary_version.id = itinerary_day.itinerary_version_id
                ORDER BY transit_leg.leg_order
                """);
        assertThat(legs).hasSize(3);
        assertThat(legs).extracting(leg -> leg.get("origin_title"))
                .containsExactly("Stop 1", "Stop 2", "Stop 3");
        assertThat(legs).extracting(leg -> leg.get("destination_title"))
                .containsExactly("Stop 2", "Stop 3", "Stop 4");
        assertThat(legs).extracting(leg -> leg.get("version_provider"))
                .containsOnly("MIXED");
        assertThat(legs.get(1)).containsEntry("provider", "DEMO")
                .containsEntry("estimated", true)
                .containsEntry("mode", "WALKING")
                .containsEntry("locked", false);
        assertThat(taskEvent.get("transit_id"))
                .isEqualTo(legs.get(1).get("id").toString());
        assertThat(taskEvent.get("from_activity_id"))
                .isEqualTo(legs.get(1).get("origin_id").toString());
        assertThat(taskEvent.get("to_activity_id"))
                .isEqualTo(legs.get(1).get("destination_id").toString());

        mockMvc.perform(get("/api/planning-tasks/{taskId}", context.taskId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.provider").value("MIXED"))
                .andExpect(jsonPath("$.requestedProviderMode")
                        .value("REAL_WITH_EXPLICIT_FALLBACK"))
                .andExpect(jsonPath("$.primaryProvider").value("AMAP"))
                .andExpect(jsonPath("$.actualProviders[0]").value("AMAP"))
                .andExpect(jsonPath("$.actualProviders[1]").value("DEMO"))
                .andExpect(jsonPath("$.fallbackAttempted").value(true))
                .andExpect(jsonPath("$.fallbackSucceeded").value(true))
                .andExpect(jsonPath("$.fallbackOperations[0].operation").value("ROUTE"))
                .andExpect(jsonPath("$.fallbackOperations[0].transitId")
                        .value(taskEvent.get("transit_id")))
                .andExpect(jsonPath("$.fallbackOperations[0].fromActivityId")
                        .value(taskEvent.get("from_activity_id")))
                .andExpect(jsonPath("$.fallbackOperations[0].toActivityId")
                        .value(taskEvent.get("to_activity_id")))
                .andExpect(jsonPath("$.fallbackOperations[0].errorCategory").value("TIMEOUT"))
                .andExpect(jsonPath("$.fallbackOperations[0].errorCode")
                        .value("PROVIDER_TIMEOUT"))
                .andExpect(jsonPath("$.fallbackOperations[0].retryCount").value(2));

        mockMvc.perform(get("/api/trips/{tripId}/itinerary", context.tripId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.provider").value("MIXED"))
                .andExpect(jsonPath("$.days[0].activities[0].source").value("AMAP"))
                .andExpect(jsonPath("$.days[0].transitLegs[1].provider").value("DEMO"))
                .andExpect(jsonPath("$.days[0].transitLegs[1].estimated").value(true));

        MvcResult stream = mockMvc.perform(get(
                        "/api/planning-tasks/{taskId}/events", context.taskId())
                        .header("Authorization", bearer(context.accessToken()))
                        .header("Last-Event-ID", queuedEventId)
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted())
                .andReturn();
        mockMvc.perform(asyncDispatch(stream))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("\"fallbackOperations\":[{")))
                .andExpect(content().string(containsString("\"operation\":\"ROUTE\"")))
                .andExpect(content().string(containsString(
                        "\"transitId\":\"" + taskEvent.get("transit_id") + "\"")));
    }

    @Test
    void leavesHistoricalCompletionV6ProviderProvenanceUnrecorded() throws Exception {
        PlanningContext context = createPlanningContext("completion-v6-legacy@example.com");
        PlanningCompletedEvent event = sharedV6Event(
                "completion-v6-legacy-amap.json", UUID.randomUUID(), context);

        completionService.handle(event);

        assertThat(jdbcTemplate.queryForObject("""
                SELECT provider FROM business.itinerary_version
                """, String.class)).isEqualTo("AMAP");
        mockMvc.perform(get("/api/planning-tasks/{taskId}", context.taskId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.provider").value("AMAP"))
                .andExpect(jsonPath("$.requestedProviderMode").doesNotExist())
                .andExpect(jsonPath("$.primaryProvider").doesNotExist())
                .andExpect(jsonPath("$.actualProviders").doesNotExist())
                .andExpect(jsonPath("$.fallbackAttempted").doesNotExist())
                .andExpect(jsonPath("$.fallbackSucceeded").doesNotExist())
                .andExpect(jsonPath("$.fallbackOperations").doesNotExist());
    }

    @Test
    void persistsExplicitPureDemoAndPureAmapProviderProvenance() throws Exception {
        String[][] cases = {
                {"completion-v6-demo.json", "DEMO_ONLY", "DEMO"},
                {"completion-v6-real-only-amap.json", "REAL_ONLY", "AMAP"}
        };
        for (String[] providerCase : cases) {
            PlanningContext context = createPlanningContext(
                    "completion-pure-" + providerCase[2].toLowerCase()
                            + "@example.com");
            PlanningCompletedEvent event = sharedV6Event(
                    providerCase[0], UUID.randomUUID(), context);

            completionService.handle(event);

            assertThat(jdbcTemplate.queryForObject("""
                    SELECT provider FROM business.itinerary_version
                    WHERE planning_task_id = ?
                    """, String.class, context.taskId())).isEqualTo(providerCase[2]);
            mockMvc.perform(get("/api/planning-tasks/{taskId}", context.taskId())
                            .header("Authorization", bearer(context.accessToken())))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.provider").value(providerCase[2]))
                    .andExpect(jsonPath("$.requestedProviderMode")
                            .value(providerCase[1]))
                    .andExpect(jsonPath("$.primaryProvider").value(providerCase[2]))
                    .andExpect(jsonPath("$.actualProviders[0]")
                            .value(providerCase[2]))
                    .andExpect(jsonPath("$.fallbackAttempted").value(false))
                    .andExpect(jsonPath("$.fallbackSucceeded").value(false))
                    .andExpect(jsonPath("$.fallbackOperations.length()").value(0));
        }
    }

    @Test
    void preservesTwoRouteFallbackOperationsWithoutDependingOnTransitOrder() throws Exception {
        PlanningContext context = createPlanningContext("completion-two-fallbacks@example.com");
        UUID eventId = UUID.randomUUID();
        ObjectNode fixture = sharedV6Fixture(
                "completion-v6-multi-transit-mixed.json", eventId, context);
        ArrayNode transitLegs = (ArrayNode) fixture.at(
                "/payload/itinerary/days/0/transitLegs");
        ((ObjectNode) transitLegs.get(0)).put("provider", "DEMO").put("estimated", true);
        ArrayNode operations = (ArrayNode) fixture.at(
                "/payload/providerProvenance/fallbackOperations");
        ObjectNode secondOperation = operations.addObject();
        secondOperation.put("operation", "ROUTE")
                .put("transitId", "20000000-0000-4000-8000-000000000033")
                .put("fromActivityId", "10000000-0000-4000-8000-000000000033")
                .put("toActivityId", "10000000-0000-4000-8000-000000000034")
                .put("requestedMode", "REAL_WITH_EXPLICIT_FALLBACK")
                .put("actualProvider", "DEMO")
                .put("errorCategory", "NETWORK_ERROR")
                .put("errorCode", "PROVIDER_NETWORK_ERROR")
                .put("retryCount", 1);

        completionService.handle(eventParser.parse(bytes(
                objectMapper.writeValueAsString(fixture))));

        List<Map<String, Object>> operationsStored = jdbcTemplate.queryForList("""
                SELECT operation ->> 'transitId' AS transit_id,
                       operation ->> 'fromActivityId' AS from_activity_id,
                       operation ->> 'toActivityId' AS to_activity_id
                FROM business.planning_task_event,
                     jsonb_array_elements(payload -> 'fallbackOperations') AS operation
                WHERE event_id = ?
                ORDER BY operation ->> 'transitId'
                """, eventId);
        assertThat(operationsStored).hasSize(2);
        assertThat(operationsStored).extracting(operation -> operation.get("transit_id"))
                .doesNotHaveDuplicates();
        assertThat(operationsStored).allSatisfy(operation -> {
            assertThat(operation.get("transit_id")).isNotNull();
            assertThat(operation.get("from_activity_id")).isNotNull();
            assertThat(operation.get("to_activity_id")).isNotNull();
        });
    }

    @Test
    void persistsAndReturnsV4KnowledgeEvidenceWithoutDuplicatingSnapshots() throws Exception {
        PlanningContext context = createPlanningContext("completion-knowledge@example.com");
        PlanningCompletedEvent event = eventParser.parse(bytes(
                PlanningCompletedEventFixture.completedAmapEventV4(
                        UUID.randomUUID(), context.traceId(), context.taskId(), context.tripId()
                )
        ));

        completionService.handle(event);
        completionService.handle(event);

        Map<String, Object> evidence = jdbcTemplate.queryForMap("""
                SELECT knowledge.status, knowledge.query, knowledge.freshness_status,
                       knowledge.freshness_checked_at, citation.document_id,
                       citation.document_version, citation.chunk_id, citation.source_url,
                       citation.similarity
                FROM business.itinerary_version_knowledge AS knowledge
                JOIN business.itinerary_knowledge_citation AS citation
                  ON citation.itinerary_version_id = knowledge.itinerary_version_id
                """);
        assertThat(evidence).containsEntry("status", "REAL")
                .containsEntry("query", "广州 历史 FRIENDS")
                .containsEntry("freshness_status", "FRESH")
                .containsEntry("document_id", "guangzhou-history-001")
                .containsEntry("document_version", 2)
                .containsEntry("chunk_id", "guangzhou-history-001-v2-c0")
                .containsEntry("source_url", "https://www.gz.gov.cn/history");
        assertThat((Double) evidence.get("similarity")).isEqualTo(0.87);
        assertThat(count("business.itinerary_version_knowledge")).isEqualTo(1);
        assertThat(count("business.itinerary_knowledge_citation")).isEqualTo(1);

        mockMvc.perform(get("/api/trips/{tripId}/itinerary", context.tripId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.knowledge.status").value("REAL"))
                .andExpect(jsonPath("$.knowledge.query").value("广州 历史 FRIENDS"))
                .andExpect(jsonPath("$.knowledge.freshness.status").value("FRESH"))
                .andExpect(jsonPath("$.knowledge.citations.length()").value(1))
                .andExpect(jsonPath("$.knowledge.citations[0].documentId")
                        .value("guangzhou-history-001"))
                .andExpect(jsonPath("$.knowledge.citations[0].documentVersion").value(2))
                .andExpect(jsonPath("$.knowledge.citations[0].sourceUrl")
                        .value("https://www.gz.gov.cn/history"));
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
    void handlesTheSameV3EventWithoutDuplicatingTransitLegs() throws Exception {
        PlanningContext context = createPlanningContext("completion-route-repeat@example.com");
        PlanningCompletedEvent event = eventParser.parse(bytes(
                PlanningCompletedEventFixture.completedAmapEventV3(
                        UUID.randomUUID(), context.traceId(), context.taskId(), context.tripId()
                )
        ));

        completionService.handle(event);
        completionService.handle(event);

        assertThat(count("business.itinerary_version")).isEqualTo(1);
        assertThat(count("business.activity")).isEqualTo(2);
        assertThat(count("business.transit_leg")).isEqualTo(1);
    }

    @Test
    void transitLegDatabaseConstraintRejectsActivitiesFromAnotherDay() throws Exception {
        PlanningContext context = createPlanningContext("completion-route-fk@example.com");
        completionService.handle(eventParser.parse(bytes(
                PlanningCompletedEventFixture.completedAmapEventV3(
                        UUID.randomUUID(), context.traceId(), context.taskId(), context.tripId()
                )
        )));
        UUID existingDayId = jdbcTemplate.queryForObject(
                "SELECT id FROM business.itinerary_day LIMIT 1", UUID.class
        );
        UUID existingActivityId = jdbcTemplate.queryForObject(
                "SELECT id FROM business.activity ORDER BY activity_order LIMIT 1", UUID.class
        );
        UUID foreignDayId = UUID.randomUUID();
        UUID foreignActivityId = UUID.randomUUID();
        UUID versionId = jdbcTemplate.queryForObject(
                "SELECT id FROM business.itinerary_version LIMIT 1", UUID.class
        );
        jdbcTemplate.update("""
                INSERT INTO business.itinerary_day(id, itinerary_version_id, day_date, day_index)
                VALUES (?, ?, DATE '2026-08-02', 1)
                """, foreignDayId, versionId);
        jdbcTemplate.update("""
                INSERT INTO business.activity(
                    id, itinerary_day_id, activity_order, title,
                    start_time, end_time, estimated_cost, source
                ) VALUES (?, ?, 0, 'Foreign day activity',
                          TIMESTAMPTZ '2026-08-02 09:00:00+08',
                          TIMESTAMPTZ '2026-08-02 10:00:00+08', 0, 'DEMO')
                """, foreignActivityId, foreignDayId);

        assertThatThrownBy(() -> jdbcTemplate.update("""
                INSERT INTO business.transit_leg(
                    id, itinerary_day_id, leg_order, from_activity_id, to_activity_id,
                    mode, distance_meters, duration_seconds, provider, estimated, polyline
                ) VALUES (?, ?, 1, ?, ?, 'WALKING', 100, 60, 'DEMO', TRUE,
                          '[{"longitude":113.3,"latitude":23.1}]'::jsonb)
                """, UUID.randomUUID(), existingDayId, existingActivityId, foreignActivityId))
                .rootCause()
                .hasMessageContaining("fk_transit_leg_destination");
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
    void rollsBackEveryCompletionWriteWhenATransitLegCannotBePersisted() throws Exception {
        PlanningContext context = createPlanningContext("completion-route-rollback@example.com");
        PlanningCompletedEvent event = eventParser.parse(bytes(
                PlanningCompletedEventFixture.completedAmapEventV3(
                        UUID.randomUUID(), context.traceId(), context.taskId(), context.tripId()
                )
        ));
        jdbcTemplate.execute("""
                CREATE FUNCTION business.fail_transit_leg_insert() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'forced transit leg failure';
                END;
                $$ LANGUAGE plpgsql
                """);
        jdbcTemplate.execute("""
                CREATE TRIGGER fail_transit_leg_insert
                BEFORE INSERT ON business.transit_leg
                FOR EACH ROW EXECUTE FUNCTION business.fail_transit_leg_insert()
                """);

        try {
            assertThatThrownBy(() -> completionService.handle(event))
                    .rootCause()
                    .hasMessageContaining("forced transit leg failure");
        } finally {
            jdbcTemplate.execute("DROP TRIGGER fail_transit_leg_insert ON business.transit_leg");
            jdbcTemplate.execute("DROP FUNCTION business.fail_transit_leg_insert()");
        }

        assertThat(taskStatus(context.taskId())).isEqualTo("QUEUED");
        assertThat(count("business.planning_task_event")).isEqualTo(1);
        assertThat(count("business.itinerary")).isZero();
        assertThat(count("business.itinerary_version")).isZero();
        assertThat(count("business.itinerary_day")).isZero();
        assertThat(count("business.activity")).isZero();
        assertThat(count("business.transit_leg")).isZero();
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
    void replaysProviderFailureMetadataThroughTheTerminalSseEvent() throws Exception {
        PlanningContext context = createPlanningContext("sse-provider-failure@example.com");
        long queuedEventId = latestTaskEventId(context.taskId());
        failureService.handle(failedEventParser.parse(bytes(
                providerFailureV2(UUID.randomUUID(), context)
        )));

        MvcResult stream = mockMvc.perform(get("/api/planning-tasks/{taskId}/events", context.taskId())
                        .header("Authorization", bearer(context.accessToken()))
                        .header("Last-Event-ID", queuedEventId)
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted())
                .andReturn();

        mockMvc.perform(asyncDispatch(stream))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("event:PLANNING_FAILED")))
                .andExpect(content().string(containsString("\"errorCategory\":\"AUTHENTICATION_ERROR\"")))
                .andExpect(content().string(containsString("\"provider\":\"AMAP\"")))
                .andExpect(content().string(containsString("\"operation\":\"POI_SEARCH\"")))
                .andExpect(content().string(containsString("\"retryCount\":0")))
                .andExpect(content().string(containsString("\"safeProviderCode\":\"10001\"")));
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

    private PlanningCompletedEvent sharedV6Event(
            String fixtureName, UUID eventId, PlanningContext context) throws Exception {
        return eventParser.parse(bytes(objectMapper.writeValueAsString(
                sharedV6Fixture(fixtureName, eventId, context))));
    }

    private ObjectNode sharedV6Fixture(
            String fixtureName, UUID eventId, PlanningContext context) throws Exception {
        ObjectNode fixture = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.sharedV6Fixture(fixtureName));
        fixture.put("eventId", eventId.toString());
        fixture.put("traceId", context.traceId().toString());
        fixture.put("taskId", context.taskId().toString());
        fixture.put("tripId", context.tripId().toString());
        return fixture;
    }

    private PlanningProgressEvent progressEvent(
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
                eventId, context.traceId(), context.taskId(), context.tripId(), stage, sequence,
                sequence * 10
        );
        return progressEventParser.parse(bytes(body));
    }

    private String providerFailureV2(UUID eventId, PlanningContext context) {
        return """
                {
                  "eventType": "PLANNING_FAILED",
                  "schemaVersion": 2,
                  "eventId": "%s",
                  "traceId": "%s",
                  "taskId": "%s",
                  "tripId": "%s",
                  "runId": "3b85b6b6-9e42-433b-90ef-d94a3eb26e18",
                  "occurredAt": "2026-07-31T00:00:00Z",
                  "payload": {
                    "status": "FAILED",
                    "errorCode": "PROVIDER_AUTHENTICATION_FAILED",
                    "errorCategory": "AUTHENTICATION_ERROR",
                    "provider": "AMAP",
                    "operation": "POI_SEARCH",
                    "retryable": false,
                    "retryCount": 0,
                    "fallbackAttempted": false,
                    "fallbackSucceeded": false,
                    "safeMessage": "AMap authentication failed",
                    "safeProviderCode": "10001",
                    "conflicts": [],
                    "relaxationSuggestions": []
                  }
                }
                """.formatted(
                eventId, context.traceId(), context.taskId(), context.tripId()
        );
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
