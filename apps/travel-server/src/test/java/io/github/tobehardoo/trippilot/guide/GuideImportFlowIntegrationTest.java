package io.github.tobehardoo.trippilot.guide;

import java.time.Instant;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedFact;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedGuide;
import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@Import(GuideImportFlowIntegrationTest.FakeClientConfiguration.class)
class GuideImportFlowIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    void importsListsAndDeduplicatesTripScopedGuideFacts() throws Exception {
        String token = register("guide-owner@example.com");
        String tripId = createTrip(token);

        MvcResult first = importGuide(token, tripId)
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.title").value("广州周末攻略"))
                .andExpect(jsonPath("$.sourceHost").value("example.com"))
                .andExpect(jsonPath("$.facts[0].category").value("TRANSPORT"))
                .andExpect(jsonPath("$.facts[0].expiresAt").value("2026-07-30T08:00:00Z"))
                .andReturn();
        String importId = json(first).get("id").asText();

        importGuide(token, tripId)
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(importId))
                .andExpect(jsonPath("$.fetchedAt").value("2026-07-24T08:00:00Z"))
                .andExpect(jsonPath("$.facts[0].observedAt").value("2026-07-24T08:00:00Z"))
                .andExpect(jsonPath("$.facts[0].expiresAt").value("2026-07-31T08:00:00Z"));

        mockMvc.perform(get("/api/trips/{tripId}/guide-imports", tripId)
                        .header("Authorization", bearer(token)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].facts.length()").value(1))
                .andExpect(jsonPath("$[0].fetchedAt").value("2026-07-24T08:00:00Z"))
                .andExpect(jsonPath("$[0].contentHash").value("a".repeat(64)));
    }

    @Test
    void hidesGuideImportsFromUsersWhoDoNotOwnTheTrip() throws Exception {
        String ownerToken = register("guide-private-owner@example.com");
        String otherToken = register("guide-private-other@example.com");
        String tripId = createTrip(ownerToken);

        importGuide(otherToken, tripId)
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("TRIP_NOT_FOUND"));

        mockMvc.perform(get("/api/trips/{tripId}/guide-imports", tripId)
                        .header("Authorization", bearer(otherToken)))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("TRIP_NOT_FOUND"));
    }

    @Test
    void importsAThousandMultibyteCharactersWithoutExceedingIndexLimits() throws Exception {
        String token = register("guide-long-fact@example.com");
        String tripId = createTrip(token);

        importGuide(token, tripId, "https://example.com/long-guide")
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.facts[0].statement").value("景".repeat(1_000)));
    }

    private org.springframework.test.web.servlet.ResultActions importGuide(
            String token, String tripId) throws Exception {
        return importGuide(token, tripId, "https://example.com/guangzhou-guide");
    }

    private org.springframework.test.web.servlet.ResultActions importGuide(
            String token, String tripId, String sourceUrl) throws Exception {
        return mockMvc.perform(post("/api/trips/{tripId}/guide-imports", tripId)
                .header("Authorization", bearer(token))
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsBytes(
                        objectMapper.createObjectNode().put("sourceUrl", sourceUrl)
                )));
    }

    private String createTrip(String token) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "广州周末",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 2000,
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
        return json(result).get("id").asText();
    }

    private String register(String email) throws Exception {
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

    private String bearer(String token) {
        return "Bearer " + token;
    }

    @TestConfiguration
    static class FakeClientConfiguration {

        @Bean
        @Primary
        GuideIntelligenceClient fakeGuideIntelligenceClient() {
            ConcurrentHashMap<String, AtomicInteger> fetchCounts = new ConcurrentHashMap<>();
            return sourceUrl -> {
                int dayOffset = fetchCounts
                        .computeIfAbsent(sourceUrl, ignored -> new AtomicInteger())
                        .getAndIncrement();
                Instant observedAt = Instant.parse("2026-07-23T08:00:00Z")
                        .plusSeconds(dayOffset * 86_400L);
                String statement = sourceUrl.endsWith("/long-guide")
                        ? "景".repeat(1_000)
                        : "从公园前乘地铁 1 号线到陈家祠站。";
                return new FetchedGuide(
                        sourceUrl,
                        sourceUrl,
                        "example.com",
                        "广州周末攻略",
                        "从公园前乘地铁 1 号线到陈家祠站。",
                        "a".repeat(64),
                        observedAt,
                        List.of(new FetchedFact(
                                "TRANSPORT",
                                statement,
                                statement,
                                0.84,
                                observedAt,
                                observedAt.plusSeconds(7 * 86_400L)
                        ))
                );
            };
        }
    }
}
