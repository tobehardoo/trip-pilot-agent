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

    private UUID createTrip(String token) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title":"Share test trip", "destination":"Guangzhou",
                                  "startDate":"2026-09-01", "endDate":"2026-09-01",
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
