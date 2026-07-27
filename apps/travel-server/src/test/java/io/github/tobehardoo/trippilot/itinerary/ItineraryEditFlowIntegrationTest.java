package io.github.tobehardoo.trippilot.itinerary;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEventParser;
import io.github.tobehardoo.trippilot.planning.PlanningCompletionService;
import io.github.tobehardoo.trippilot.support.PlanningCompletedEventFixture;
import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ItineraryEditFlowIntegrationTest extends PostgresIntegrationTest {

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
    void previewsDeletionWithoutChangingTheCurrentVersion() throws Exception {
        PlanningContext context = completedItinerary("edit-preview@example.com");
        JsonNode current = currentItinerary(context);
        UUID versionId = uuid(current, "versionId");
        UUID activityId = uuid(current.at("/days/0/activities/0"), "id");

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits/preview", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(versionId, "DELETE_ACTIVITY", activityId, null)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.operation").value("DELETE_ACTIVITY"))
                .andExpect(jsonPath("$.canApply").value(true))
                .andExpect(jsonPath("$.impactedDates[0]").value("2026-08-01"))
                .andExpect(jsonPath("$.impactedActivityIds[0]").value(activityId.toString()))
                .andExpect(jsonPath("$.warnings[0]").isNotEmpty())
                .andExpect(jsonPath("$.blockingReasons").isEmpty());

        assertThat(uuid(currentItinerary(context), "versionId")).isEqualTo(versionId);
        assertThat(count("business.itinerary_version")).isEqualTo(1);
    }

    @Test
    void deletesAnActivityByCreatingANewImmutableVersion() throws Exception {
        PlanningContext context = completedItinerary("edit-delete@example.com");
        JsonNode current = currentItinerary(context);
        UUID versionId = uuid(current, "versionId");
        UUID activityId = uuid(current.at("/days/0/activities/0"), "id");

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(versionId, "DELETE_ACTIVITY", activityId, null)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.versionNumber").value(2))
                .andExpect(jsonPath("$.parentVersionId").value(versionId.toString()))
                .andExpect(jsonPath("$.days[0].activities.length()").value(1))
                .andExpect(jsonPath("$.days[0].activities[0].locked").value(false))
                .andExpect(jsonPath("$.days[0].transitLegs").isEmpty());

        assertThat(count("business.itinerary_version")).isEqualTo(2);
        assertThat(jdbcTemplate.queryForObject("""
                SELECT version_source
                FROM business.itinerary_version
                WHERE itinerary_id = (SELECT id FROM business.itinerary WHERE trip_id = ?)
                ORDER BY version_number DESC
                LIMIT 1
                """, String.class, context.tripId())).isEqualTo("USER_EDIT");
    }

    @Test
    void listsDiffsAndIdempotentlyRollsBackByCreatingANewVersion() throws Exception {
        PlanningContext context = completedItinerary("version-rollback@example.com");
        JsonNode initial = currentItinerary(context);
        UUID initialVersionId = uuid(initial, "versionId");
        UUID activityId = uuid(initial.at("/days/0/activities/0"), "id");
        JsonNode edited = json(mockMvc.perform(post(
                                "/api/trips/{tripId}/itinerary/edits",
                                context.tripId()
                        )
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(
                                initialVersionId,
                                "DELETE_ACTIVITY",
                                activityId,
                                null
                        )))
                .andExpect(status().isOk())
                .andReturn());
        UUID editedVersionId = uuid(edited, "versionId");

        mockMvc.perform(get(
                                "/api/trips/{tripId}/itinerary/versions",
                                context.tripId()
                        )
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[0].versionNumber").value(2))
                .andExpect(jsonPath("$[0].current").value(true))
                .andExpect(jsonPath("$[0].versionSource").value("USER_EDIT"));

        mockMvc.perform(get(
                                "/api/trips/{tripId}/itinerary/versions/{versionId}",
                                context.tripId(),
                                initialVersionId
                        )
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.versionId")
                        .value(initialVersionId.toString()))
                .andExpect(jsonPath("$.days[0].activities.length()").value(2));

        mockMvc.perform(get(
                                "/api/trips/{tripId}/itinerary/versions/diff",
                                context.tripId()
                        )
                        .queryParam("from", initialVersionId.toString())
                        .queryParam("to", editedVersionId.toString())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.removedActivities.length()").value(1))
                .andExpect(jsonPath("$.addedActivities").isEmpty())
                .andExpect(jsonPath("$.addedFactImpacts").isEmpty())
                .andExpect(jsonPath("$.removedFactImpacts").isEmpty())
                .andExpect(jsonPath("$.changedFactImpacts").isEmpty());

        UUID idempotencyKey = UUID.randomUUID();
        String rollbackBody = """
                {
                  "sourceVersionId": "%s",
                  "expectedCurrentVersionId": "%s"
                }
                """.formatted(initialVersionId, editedVersionId);
        MvcResult firstRollback = mockMvc.perform(post(
                                "/api/trips/{tripId}/itinerary/rollbacks",
                                context.tripId()
                        )
                        .header("Authorization", bearer(context.accessToken()))
                        .header("Idempotency-Key", idempotencyKey)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(rollbackBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.versionNumber").value(3))
                .andExpect(jsonPath("$.rollbackFromVersionId")
                        .value(initialVersionId.toString()))
                .andExpect(jsonPath("$.days[0].activities.length()").value(2))
                .andReturn();
        String rollbackVersionId = json(firstRollback).get("versionId").asText();
        UUID rollbackActivityId = uuid(
                json(firstRollback).at("/days/0/activities/0"),
                "id"
        );
        mockMvc.perform(post(
                                "/api/trips/{tripId}/itinerary/edits",
                                context.tripId()
                        )
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(
                                UUID.fromString(rollbackVersionId),
                                "LOCK_ACTIVITY",
                                rollbackActivityId,
                                null
                        )))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.versionNumber").value(4));

        mockMvc.perform(post(
                                "/api/trips/{tripId}/itinerary/rollbacks",
                                context.tripId()
                        )
                        .header("Authorization", bearer(context.accessToken()))
                        .header("Idempotency-Key", idempotencyKey)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(rollbackBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.versionId").value(rollbackVersionId))
                .andExpect(jsonPath("$.versionNumber").value(3))
                .andExpect(jsonPath("$.rollbackFromVersionId")
                        .value(initialVersionId.toString()));

        assertThat(count("business.itinerary_version")).isEqualTo(4);
        assertThat(count("business.itinerary_rollback")).isEqualTo(1);
    }

    @Test
    void keepsRepeatedVisitsDistinctWhenCalculatingVersionDiffs() throws Exception {
        PlanningContext context = completedItinerary("version-duplicate-poi@example.com");
        JsonNode initial = currentItinerary(context);
        UUID initialVersionId = uuid(initial, "versionId");
        UUID firstActivityId = uuid(initial.at("/days/0/activities/0"), "id");
        UUID secondActivityId = uuid(initial.at("/days/0/activities/1"), "id");
        String firstTitle = initial.at("/days/0/activities/0/title").asText();
        String firstProviderPoiId = jdbcTemplate.queryForObject("""
                SELECT provider_poi_id
                FROM business.activity
                WHERE id = ?
                """, String.class, firstActivityId);
        jdbcTemplate.update("""
                UPDATE business.activity
                SET title = ?, provider_poi_id = ?
                WHERE id = ?
                """, firstTitle, firstProviderPoiId, secondActivityId);

        JsonNode edited = json(mockMvc.perform(post(
                                "/api/trips/{tripId}/itinerary/edits",
                                context.tripId()
                        )
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(
                                initialVersionId,
                                "DELETE_ACTIVITY",
                                firstActivityId,
                                null
                        )))
                .andExpect(status().isOk())
                .andReturn());

        mockMvc.perform(get(
                                "/api/trips/{tripId}/itinerary/versions/diff",
                                context.tripId()
                        )
                        .queryParam("from", initialVersionId.toString())
                        .queryParam("to", uuid(edited, "versionId").toString())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.removedActivities.length()").value(1))
                .andExpect(jsonPath("$.addedActivities").isEmpty())
                .andExpect(jsonPath("$.changedActivities.length()").value(1))
                .andExpect(jsonPath("$.changedActivities[0].changes[0]")
                        .value("MOVED"));
    }

    @Test
    void locksAnActivityAndRejectsMovingItWithAnExplanation() throws Exception {
        PlanningContext context = completedItinerary("edit-lock@example.com");
        JsonNode current = currentItinerary(context);
        UUID versionId = uuid(current, "versionId");
        UUID activityId = uuid(current.at("/days/0/activities/0"), "id");

        MvcResult lockResult = mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(versionId, "LOCK_ACTIVITY", activityId, null)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.versionNumber").value(2))
                .andExpect(jsonPath("$.days[0].activities[0].locked").value(true))
                .andReturn();
        JsonNode locked = json(lockResult);
        UUID lockedVersionId = uuid(locked, "versionId");
        UUID lockedActivityId = uuid(locked.at("/days/0/activities/0"), "id");
        String move = """
                ,
                "targetDate": "2026-08-01",
                "targetOrder": 1,
                "targetStartTime": "2026-08-01T15:30:00+08:00",
                "targetEndTime": "2026-08-01T17:30:00+08:00"
                """;

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits/preview", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(lockedVersionId, "MOVE_ACTIVITY", lockedActivityId, move)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.canApply").value(false))
                .andExpect(jsonPath("$.blockingReasons[0].code").value("ITINERARY_ACTIVITY_LOCKED"))
                .andExpect(jsonPath("$.blockingReasons[0].message").isNotEmpty());

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(lockedVersionId, "MOVE_ACTIVITY", lockedActivityId, move)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("ITINERARY_ACTIVITY_LOCKED"));

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits/preview", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(lockedVersionId, "DELETE_ACTIVITY", lockedActivityId, null)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.canApply").value(false))
                .andExpect(jsonPath("$.blockingReasons[0].code").value("ITINERARY_ACTIVITY_LOCKED"));

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(lockedVersionId, "DELETE_ACTIVITY", lockedActivityId, null)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("ITINERARY_ACTIVITY_LOCKED"));
    }

    @Test
    void persistsTransitModeAndLockInANewItineraryVersion() throws Exception {
        PlanningContext context = completedItinerary("edit-transit@example.com");
        JsonNode current = currentItinerary(context);
        UUID versionId = uuid(current, "versionId");
        UUID legId = uuid(current.at("/days/0/transitLegs/0"), "id");

        MvcResult transitEdit = mockMvc.perform(post(
                                "/api/trips/{tripId}/itinerary/edits",
                                context.tripId()
                        )
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(transitEditJson(versionId, legId, "DRIVING", true)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.versionNumber").value(2))
                .andExpect(jsonPath("$.days[0].transitLegs[0].mode").value("DRIVING"))
                .andExpect(jsonPath("$.days[0].transitLegs[0].provider").value("DEMO"))
                .andExpect(jsonPath("$.days[0].transitLegs[0].estimated").value(true))
                .andExpect(jsonPath("$.days[0].transitLegs[0].polyline").isEmpty())
                .andExpect(jsonPath("$.days[0].transitLegs[0].locked").value(true))
                .andReturn();
        UUID editedVersionId = uuid(json(transitEdit), "versionId");

        mockMvc.perform(get(
                                "/api/trips/{tripId}/itinerary/versions/diff",
                                context.tripId()
                        )
                        .queryParam("from", versionId.toString())
                        .queryParam("to", editedVersionId.toString())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.changedTransitLegs.length()").value(1))
                .andExpect(jsonPath("$.changedTransitLegs[0].changes")
                        .value(org.hamcrest.Matchers.hasItems(
                                "MODE_CHANGED", "LOCK_CHANGED"
                        )));

        JsonNode persisted = currentItinerary(context);
        assertThat(persisted.at("/days/0/transitLegs/0/mode").asText()).isEqualTo("DRIVING");
        assertThat(persisted.at("/days/0/transitLegs/0/locked").asBoolean()).isTrue();
    }

    @Test
    void rejectsFullPlanningWhileAnActivityIsLocked() throws Exception {
        PlanningContext context = completedItinerary("planning-locked-activity@example.com");
        JsonNode current = currentItinerary(context);
        UUID versionId = uuid(current, "versionId");
        UUID activityId = uuid(current.at("/days/0/activities/0"), "id");

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(versionId, "LOCK_ACTIVITY", activityId, null)))
                .andExpect(status().isOk());

        mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .header("Idempotency-Key", UUID.randomUUID()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("ITINERARY_LOCKED_ACTIVITIES"));
    }

    @Test
    void movesAnUnlockedActivityAndRejectsOverlappingTimes() throws Exception {
        PlanningContext context = completedItinerary("edit-move@example.com");
        JsonNode current = currentItinerary(context);
        UUID versionId = uuid(current, "versionId");
        UUID activityId = uuid(current.at("/days/0/activities/1"), "id");
        String validMove = """
                ,
                "targetDate": "2026-08-01",
                "targetOrder": 0,
                "targetStartTime": "2026-08-01T06:30:00+08:00",
                "targetEndTime": "2026-08-01T08:30:00+08:00"
                """;

        MvcResult movedResult = mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(versionId, "MOVE_ACTIVITY", activityId, validMove)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.versionNumber").value(2))
                .andExpect(jsonPath("$.days[0].activities[0].startTime")
                        .value("2026-07-31T22:30:00Z"))
                .andReturn();

        JsonNode moved = json(movedResult);
        UUID movedVersionId = uuid(moved, "versionId");
        UUID movedActivityId = uuid(moved.at("/days/0/activities/0"), "id");
        String overlappingMove = """
                ,
                "targetDate": "2026-08-01",
                "targetOrder": 0,
                "targetStartTime": "2026-08-01T09:30:00+08:00",
                "targetEndTime": "2026-08-01T10:30:00+08:00"
                """;

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits/preview", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(movedVersionId, "MOVE_ACTIVITY", movedActivityId, overlappingMove)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.canApply").value(false))
                .andExpect(jsonPath("$.blockingReasons[0].code").value("ITINERARY_ACTIVITY_CONFLICT"));

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(movedVersionId, "MOVE_ACTIVITY", movedActivityId, overlappingMove)))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.code").value("ITINERARY_ACTIVITY_CONFLICT"));
    }

    @Test
    void rejectsAnEditBasedOnAStaleVersion() throws Exception {
        PlanningContext context = completedItinerary("edit-stale@example.com");
        JsonNode current = currentItinerary(context);
        UUID versionId = uuid(current, "versionId");
        UUID activityId = uuid(current.at("/days/0/activities/0"), "id");

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(versionId, "LOCK_ACTIVITY", activityId, null)))
                .andExpect(status().isOk());

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(versionId, "DELETE_ACTIVITY", activityId, null)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("ITINERARY_VERSION_CONFLICT"));
    }

    @Test
    void rejectsEditsWhilePlanningTaskIsActive() throws Exception {
        PlanningContext context = completedItinerary("edit-planning-active@example.com");
        JsonNode current = currentItinerary(context);
        UUID versionId = uuid(current, "versionId");
        UUID activityId = uuid(current.at("/days/0/activities/0"), "id");

        mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .header("Idempotency-Key", UUID.randomUUID()))
                .andExpect(status().isAccepted());

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits/preview", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(versionId, "DELETE_ACTIVITY", activityId, null)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.canApply").value(false))
                .andExpect(jsonPath("$.blockingReasons[0].code").value("ITINERARY_PLANNING_ACTIVE"));

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(versionId, "DELETE_ACTIVITY", activityId, null)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("ITINERARY_PLANNING_ACTIVE"));
    }

    @Test
    void replansOnlyTheImpactedDateAndPreservesLockedUnaffectedContent() throws Exception {
        PlanningContext context = completedTwoDayItinerary("local-replan@example.com");
        JsonNode current = currentItinerary(context);
        UUID secondDayActivityId = uuid(current.at("/days/1/activities/0"), "id");
        JsonNode locked = json(mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(uuid(current, "versionId"), "LOCK_ACTIVITY", secondDayActivityId, null)))
                .andExpect(status().isOk())
                .andReturn());
        UUID activityToMove = uuid(locked.at("/days/0/activities/1"), "id");
        String move = """
                ,
                "targetDate": "2026-08-01",
                "targetOrder": 0,
                "targetStartTime": "2026-08-01T06:30:00+08:00",
                "targetEndTime": "2026-08-01T08:30:00+08:00"
                """;
        JsonNode edited = json(mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(uuid(locked, "versionId"), "MOVE_ACTIVITY", activityToMove, move)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.days[0].transitLegs").isEmpty())
                .andExpect(jsonPath("$.days[1].transitLegs[0].distanceMeters").value(910))
                .andReturn());

        MvcResult taskResult = mockMvc.perform(post("/api/trips/{tripId}/itinerary/replans", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .header("Idempotency-Key", UUID.randomUUID())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(replanJson(uuid(edited, "versionId"), "2026-08-01")))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.taskType").value("REPLAN"))
                .andReturn();
        UUID taskId = uuid(json(taskResult), "taskId");
        JsonNode command = replanCommand(taskId);
        assertThat(command.at("/payload/impactedDates/0").asText()).isEqualTo("2026-08-01");
        assertThat(command.at("/payload/itinerary/days/1/transitLegs/0/distanceMeters").asInt())
                .isEqualTo(910);

        completionService.handle(replanCompletedEvent(context.tripId(), taskId, command, 777));

        JsonNode replanned = currentItinerary(context);
        assertThat(replanned.get("versionNumber").asInt()).isEqualTo(4);
        assertThat(replanned.get("parentVersionId").asText()).isEqualTo(uuid(edited, "versionId").toString());
        assertThat(replanned.at("/days/0/transitLegs/0/distanceMeters").asInt()).isEqualTo(777);
        assertThat(replanned.at("/days/1/transitLegs/0/distanceMeters").asInt()).isEqualTo(910);
        assertThat(replanned.at("/days/1/activities/0/title").asText()).isEqualTo("Yuexiu Park");
        assertThat(replanned.at("/days/1/activities/0/locked").asBoolean()).isTrue();
        assertThat(jdbcTemplate.queryForObject("""
                SELECT version_source FROM business.itinerary_version WHERE id = ?
                """, String.class, uuid(replanned, "versionId"))).isEqualTo("LOCAL_REPLAN");
    }

    @Test
    void failsAReplanWhoseBaselineItineraryIsNoLongerCurrent() throws Exception {
        PlanningContext context = completedTwoDayItinerary("local-replan-stale@example.com");
        JsonNode baseline = currentItinerary(context);
        MvcResult taskResult = mockMvc.perform(post("/api/trips/{tripId}/itinerary/replans", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .header("Idempotency-Key", UUID.randomUUID())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(replanJson(uuid(baseline, "versionId"), "2026-08-01")))
                .andExpect(status().isAccepted())
                .andReturn();
        UUID taskId = uuid(json(taskResult), "taskId");
        JsonNode command = replanCommand(taskId);

        jdbcTemplate.update("UPDATE business.planning_task SET status = 'CANCELLED' WHERE id = ?", taskId);
        UUID activityId = uuid(baseline.at("/days/1/activities/0"), "id");
        JsonNode newer = json(mockMvc.perform(post("/api/trips/{tripId}/itinerary/edits", context.tripId())
                        .header("Authorization", bearer(context.accessToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(editJson(uuid(baseline, "versionId"), "LOCK_ACTIVITY", activityId, null)))
                .andExpect(status().isOk())
                .andReturn());
        jdbcTemplate.update("""
                UPDATE business.planning_task
                SET status = 'QUEUED', version = version + 1
                WHERE id = ?
                """, taskId);

        completionService.handle(replanCompletedEvent(context.tripId(), taskId, command, 777));

        assertThat(uuid(currentItinerary(context), "versionId")).isEqualTo(uuid(newer, "versionId"));
        assertThat(jdbcTemplate.queryForObject(
                "SELECT error_code FROM business.planning_task WHERE id = ?", String.class, taskId
        )).isEqualTo("STALE_ITINERARY_VERSION");
    }

    private PlanningContext completedItinerary(String email) throws Exception {
        String accessToken = registerAndGetAccessToken(email);
        UUID tripId = createTrip(accessToken);
        MvcResult taskResult = mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", tripId)
                        .header("Authorization", bearer(accessToken))
                        .header("Idempotency-Key", UUID.randomUUID()))
                .andExpect(status().isAccepted())
                .andReturn();
        UUID taskId = uuid(json(taskResult), "taskId");
        UUID traceId = jdbcTemplate.queryForObject(
                "SELECT trace_id FROM business.planning_task WHERE id = ?", UUID.class, taskId
        );
        PlanningCompletedEvent event = eventParser.parse(
                PlanningCompletedEventFixture.completedAmapEventV3(
                        UUID.randomUUID(), traceId, taskId, tripId
                ).getBytes(StandardCharsets.UTF_8)
        );
        completionService.handle(event);
        return new PlanningContext(accessToken, tripId);
    }

    private PlanningContext completedTwoDayItinerary(String email) throws Exception {
        String accessToken = registerAndGetAccessToken(email);
        UUID tripId = createTrip(accessToken, "2026-08-02");
        MvcResult taskResult = mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", tripId)
                        .header("Authorization", bearer(accessToken))
                        .header("Idempotency-Key", UUID.randomUUID()))
                .andExpect(status().isAccepted())
                .andReturn();
        UUID taskId = uuid(json(taskResult), "taskId");
        UUID traceId = jdbcTemplate.queryForObject(
                "SELECT trace_id FROM business.planning_task WHERE id = ?", UUID.class, taskId
        );
        completionService.handle(eventParser.parse(
                PlanningCompletedEventFixture.completedTwoDayAmapEventV3(
                        UUID.randomUUID(), traceId, taskId, tripId
                ).getBytes(StandardCharsets.UTF_8)
        ));
        return new PlanningContext(accessToken, tripId);
    }

    private UUID createTrip(String accessToken) throws Exception {
        return createTrip(accessToken, "2026-08-01");
    }

    private UUID createTrip(String accessToken, String endDate) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "Guangzhou day trip",
                                  "destination": "Guangzhou",
                                  "startDate": "2026-08-01",
                                  "endDate": "%s",
                                  "constraints": {
                                    "budgetAmount": 1000,
                                    "travelers": 2,
                                    "travelerType": "FRIENDS",
                                    "pace": "BALANCED",
                                    "preferences": ["history"],
                                    "fixedSchedules": []
                                  }
                                }
                                """.formatted(endDate)))
                .andExpect(status().isCreated())
                .andReturn();
        return uuid(json(result), "id");
    }

    private String replanJson(UUID versionId, String date) {
        return """
                {
                  "baseVersionId": "%s",
                  "dates": ["%s"]
                }
                """.formatted(versionId, date);
    }

    private JsonNode replanCommand(UUID taskId) throws Exception {
        String payload = jdbcTemplate.queryForObject("""
                SELECT payload::text
                FROM business.outbox_event
                WHERE aggregate_id = ? AND event_type = 'PLANNING_REPLAN_REQUESTED'
                """, String.class, taskId);
        return objectMapper.readTree(payload);
    }

    private PlanningCompletedEvent replanCompletedEvent(
            UUID tripId, UUID taskId, JsonNode command, int distanceMeters) throws Exception {
        ObjectNode itinerary = command.at("/payload/itinerary").deepCopy();
        String provider = itinerary.remove("provider").asText();
        ArrayNode activities = (ArrayNode) itinerary.at("/days/0/activities");
        ObjectNode transit = objectMapper.createObjectNode();
        transit.put("fromActivityIndex", 0);
        transit.put("toActivityIndex", 1);
        transit.put("mode", "WALKING");
        transit.put("distanceMeters", distanceMeters);
        transit.put("durationSeconds", 480);
        transit.put("provider", "AMAP");
        transit.put("estimated", false);
        ArrayNode polyline = transit.putArray("polyline");
        polyline.add(activities.get(0).get("coordinates"));
        polyline.add(activities.get(1).get("coordinates"));
        ((ObjectNode) itinerary.at("/days/0")).putArray("transitLegs").add(transit);

        UUID traceId = UUID.fromString(command.get("traceId").asText());
        ObjectNode root = objectMapper.createObjectNode();
        root.put("eventType", "PLANNING_COMPLETED");
        root.put("schemaVersion", 5);
        root.put("eventId", UUID.randomUUID().toString());
        root.put("traceId", traceId.toString());
        root.put("taskId", taskId.toString());
        root.put("tripId", tripId.toString());
        root.put("runId", UUID.randomUUID().toString());
        root.put("occurredAt", "2026-07-24T05:00:00Z");
        ObjectNode payload = root.putObject("payload");
        payload.put("provider", provider);
        ObjectNode knowledge = command.at("/payload/knowledge").deepCopy();
        ((ObjectNode) knowledge.get("freshness")).remove("checkedAt");
        ((ObjectNode) knowledge.get("freshness")).remove("staleReason");
        payload.set("knowledge", knowledge);
        payload.set("itinerary", itinerary);
        return eventParser.parse(objectMapper.writeValueAsBytes(root));
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

    private JsonNode currentItinerary(PlanningContext context) throws Exception {
        MvcResult result = mockMvc.perform(get("/api/trips/{tripId}/itinerary", context.tripId())
                        .header("Authorization", bearer(context.accessToken())))
                .andExpect(status().isOk())
                .andReturn();
        return json(result);
    }

    private String editJson(UUID versionId, String operation, UUID activityId, String extraFields) {
        String extra = extraFields == null ? "" : extraFields;
        return """
                {
                  "baseVersionId": "%s",
                  "operation": "%s",
                  "activityId": "%s"%s
                }
                """.formatted(versionId, operation, activityId, extra);
    }

    private String transitEditJson(UUID versionId, UUID legId, String mode, boolean locked) {
        return """
                {
                  "baseVersionId": "%s",
                  "operation": "UPDATE_TRANSIT_LEG",
                  "transitLegId": "%s",
                  "transitMode": "%s",
                  "transitLocked": %s
                }
                """.formatted(versionId, legId, mode, locked);
    }

    private int count(String table) {
        Integer result = jdbcTemplate.queryForObject("SELECT count(*) FROM " + table, Integer.class);
        return result == null ? 0 : result;
    }

    private JsonNode json(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsByteArray());
    }

    private UUID uuid(JsonNode node, String field) {
        return UUID.fromString(node.get(field).asText());
    }

    private String bearer(String accessToken) {
        return "Bearer " + accessToken;
    }

    private record PlanningContext(String accessToken, UUID tripId) {
    }
}
