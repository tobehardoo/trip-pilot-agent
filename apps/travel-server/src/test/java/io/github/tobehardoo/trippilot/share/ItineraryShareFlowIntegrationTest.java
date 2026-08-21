package io.github.tobehardoo.trippilot.share;

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

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ItineraryShareFlowIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void createsRevokesAndResolvesAnImmutableAnonymousItineraryShare() throws Exception {
        String ownerToken = registerAndGetAccessToken("share-owner@example.com");
        UUID tripId = createTrip(ownerToken);
        UUID versionId = seedCurrentVersion(tripId);

        MvcResult create = mockMvc.perform(post("/api/trips/{tripId}/itinerary/shares", tripId)
                        .header("Authorization", bearer(ownerToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"versionId":"%s","expiresAt":"2026-12-31T23:59:59Z"}
                                """.formatted(versionId)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.shareToken").isNotEmpty())
                .andExpect(jsonPath("$.versionId").value(versionId.toString()))
                .andReturn();

        JsonNode share = json(create);
        String token = share.get("shareToken").asText();
        String shareId = share.get("id").asText();
        String storedTokenHash = jdbcTemplate.queryForObject(
                "SELECT token_hash FROM business.itinerary_share WHERE id = ?::uuid", String.class, shareId
        );
        assertThat(storedTokenHash).doesNotContain(token).hasSize(64);

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/shares", tripId)
                        .header("Authorization", bearer(ownerToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"versionId":"%s"}
                                """.formatted(versionId)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("SHARE_ACTIVE"));

        mockMvc.perform(get("/api/shares/{shareToken}", token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("Share-safe itinerary"))
                .andExpect(jsonPath("$.estimatedTotalCost").value(88))
                .andExpect(jsonPath("$.versionId").doesNotExist())
                .andExpect(jsonPath("$.ownerId").doesNotExist())
                .andExpect(jsonPath("$.planningTaskId").doesNotExist());

        mockMvc.perform(delete("/api/trips/{tripId}/itinerary/shares/{shareId}", tripId, shareId)
                        .header("Authorization", bearer(ownerToken)))
                .andExpect(status().isNoContent());
        mockMvc.perform(get("/api/shares/{shareToken}", token))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("SHARE_NOT_FOUND"));

        MvcResult reissued = mockMvc.perform(post("/api/trips/{tripId}/itinerary/shares", tripId)
                        .header("Authorization", bearer(ownerToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"versionId":"%s"}
                                """.formatted(versionId)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.shareToken").isNotEmpty())
                .andReturn();

        String expiredShareId = json(reissued).get("id").asText();
        jdbcTemplate.update("""
                UPDATE business.itinerary_share
                SET expires_at = NOW() - INTERVAL '1 second'
                WHERE id = ?::uuid
                """, expiredShareId);

        mockMvc.perform(post("/api/trips/{tripId}/itinerary/shares", tripId)
                        .header("Authorization", bearer(ownerToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"versionId":"%s"}
                                """.formatted(versionId)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.shareToken").isNotEmpty());
    }

    @Test
    void exposesStableTaxiPresentationAndHidesDrivingTollFromPublicShares() throws Exception {
        String ownerToken = registerAndGetAccessToken("share-transit@example.com");
        UUID tripId = createTrip(ownerToken);
        UUID versionId = seedCurrentVersionWithRoadLegs(tripId);

        MvcResult created = mockMvc.perform(post("/api/trips/{tripId}/itinerary/shares", tripId)
                        .header("Authorization", bearer(ownerToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"versionId":"%s"}
                                """.formatted(versionId)))
                .andExpect(status().isCreated())
                .andReturn();
        String token = json(created).get("shareToken").asText();

        mockMvc.perform(get("/api/shares/{shareToken}", token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.estimatedTotalCost").value(107.80))
                .andExpect(jsonPath("$.days[0].transitLegs[0].mode").value("DRIVING"))
                .andExpect(jsonPath("$.days[0].transitLegs[0].modeLabel").value("打车"))
                .andExpect(jsonPath("$.days[0].transitLegs[0].routeDurationSeconds").value(900))
                .andExpect(jsonPath("$.days[0].transitLegs[0].waitSeconds").value(0))
                .andExpect(jsonPath("$.days[0].transitLegs[0].costMeaning").value("ROAD_TOLL"))
                .andExpect(jsonPath("$.days[0].transitLegs[0].estimatedCost").doesNotExist())
                .andExpect(jsonPath("$.days[0].transitLegs[1].mode").value("TAXI"))
                .andExpect(jsonPath("$.days[0].transitLegs[1].modeLabel").value("打车"))
                .andExpect(jsonPath("$.days[0].transitLegs[1].routeDurationSeconds").value(900))
                .andExpect(jsonPath("$.days[0].transitLegs[1].waitSeconds").value(300))
                .andExpect(jsonPath("$.days[0].transitLegs[1].costSource").value("RULE_ESTIMATE"))
                .andExpect(jsonPath("$.days[0].transitLegs[1].estimatedCost").value(19.80));
    }

    private UUID seedCurrentVersion(UUID tripId) {
        UUID itineraryId = UUID.randomUUID();
        UUID versionId = UUID.randomUUID();
        jdbcTemplate.update("INSERT INTO business.itinerary(id, trip_id) VALUES (?, ?)", itineraryId, tripId);
        jdbcTemplate.update("""
                INSERT INTO business.itinerary_version(
                    id, itinerary_id, version_number, version_source, title,
                    estimated_total_cost, provider, constraint_snapshot
                ) VALUES (?, ?, 1, 'PLANNING_TASK', 'Share-safe itinerary', 88, 'DEMO', '{}'::jsonb)
                """, versionId, itineraryId);
        jdbcTemplate.update("UPDATE business.itinerary SET current_version_id = ? WHERE id = ?", versionId, itineraryId);
        return versionId;
    }

    private UUID seedCurrentVersionWithRoadLegs(UUID tripId) {
        UUID itineraryId = UUID.randomUUID();
        UUID versionId = UUID.randomUUID();
        UUID dayId = UUID.randomUUID();
        UUID firstActivityId = UUID.randomUUID();
        UUID secondActivityId = UUID.randomUUID();
        UUID thirdActivityId = UUID.randomUUID();
        jdbcTemplate.update("INSERT INTO business.itinerary(id, trip_id) VALUES (?, ?)",
                itineraryId, tripId);
        jdbcTemplate.update("""
                INSERT INTO business.itinerary_version(
                    id, itinerary_id, version_number, version_source, title,
                    estimated_total_cost, provider, constraint_snapshot
                ) VALUES (?, ?, 1, 'PLANNING_TASK', 'Road semantics', 114.30, 'AMAP', '{}'::jsonb)
                """, versionId, itineraryId);
        jdbcTemplate.update("""
                INSERT INTO business.itinerary_day(id, itinerary_version_id, day_date, day_index)
                VALUES (?, ?, DATE '2026-08-01', 0)
                """, dayId, versionId);
        seedActivity(firstActivityId, dayId, 0, "Origin", "09:00", "10:00", 113.26, 23.13);
        seedActivity(secondActivityId, dayId, 1, "Middle", "10:20", "11:20", 113.28, 23.12);
        seedActivity(thirdActivityId, dayId, 2, "Destination", "11:40", "12:40", 113.31, 23.10);
        jdbcTemplate.update("""
                INSERT INTO business.transit_leg(
                    id, itinerary_day_id, leg_order, from_activity_id, to_activity_id,
                    mode, distance_meters, duration_seconds, provider, estimated,
                    polyline, estimated_cost
                ) VALUES (?, ?, 0, ?, ?, 'DRIVING', 3200, 900, 'AMAP', FALSE,
                    '[{"longitude":113.26,"latitude":23.13},
                      {"longitude":113.28,"latitude":23.12}]'::jsonb, 6.50)
                """, UUID.randomUUID(), dayId, firstActivityId, secondActivityId);
        jdbcTemplate.update("""
                INSERT INTO business.transit_leg(
                    id, itinerary_day_id, leg_order, from_activity_id, to_activity_id,
                    mode, distance_meters, duration_seconds, provider, estimated,
                    polyline, estimated_cost
                ) VALUES (?, ?, 1, ?, ?, 'TAXI', 3000, 1200, 'AMAP', TRUE,
                    '[{"longitude":113.28,"latitude":23.12},
                      {"longitude":113.31,"latitude":23.10}]'::jsonb, 19.80)
                """, UUID.randomUUID(), dayId, secondActivityId, thirdActivityId);
        jdbcTemplate.update("UPDATE business.itinerary SET current_version_id = ? WHERE id = ?",
                versionId, itineraryId);
        return versionId;
    }

    private void seedActivity(
            UUID activityId,
            UUID dayId,
            int order,
            String title,
            String start,
            String end,
            double longitude,
            double latitude
    ) {
        jdbcTemplate.update("""
                INSERT INTO business.activity(
                    id, itinerary_day_id, activity_order, title, start_time, end_time,
                    estimated_cost, source, provider_poi_id, longitude, latitude,
                    address, locked
                ) VALUES (?, ?, ?, ?,
                    CAST('2026-08-01T%s:00+08:00' AS timestamptz),
                    CAST('2026-08-01T%s:00+08:00' AS timestamptz),
                    25, 'AMAP', ?, ?, ?, ?, FALSE)
                """.formatted(start, end), activityId, dayId, order, title,
                "poi-" + order, longitude, latitude, title + " address");
    }

    private UUID createTrip(String token) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title":"Share test trip", "destination":"Guangzhou",
                                  "startDate":"2026-08-01", "endDate":"2026-08-01",
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
}
