package io.github.tobehardoo.trippilot.guide;

import java.time.Instant;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.atomic.AtomicInteger;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedFact;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedGuide;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedMergeDecision;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedModelExtraction;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedNormalizedDocument;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedTrustedFact;
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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.junit.jupiter.api.Assertions.assertEquals;

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
                .andExpect(jsonPath("$.sourceType").value("PUBLIC_GUIDE_URL"))
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
    void importsUserProvidedTextWithoutRequiringAPublicUrl() throws Exception {
        String token = register("guide-text-owner@example.com");
        String tripId = createTrip(token);

        mockMvc.perform(post("/api/trips/{tripId}/guide-imports", tripId)
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "sourceType": "XIAOHONGSHU_SHARED_TEXT",
                                  "title": "广州塔分享正文",
                                  "content": "广州塔地址是阅江西路222号，门票约150元，建议提前购票。"
                                }
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.sourceType").value("XIAOHONGSHU_SHARED_TEXT"))
                .andExpect(jsonPath("$.sourceHost").value("小红书分享文本"))
                .andExpect(jsonPath("$.facts[0].category").value("LOCATION"));
    }

    @Test
    void persistsImageOcrImportsIntoTheSameEvidenceStore() throws Exception {
        String token = register("guide-image-owner@example.com");
        String tripId = createTrip(token);

        mockMvc.perform(post("/api/trips/{tripId}/guide-imports", tripId)
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "sourceType": "IMAGE_OCR",
                                  "images": [
                                    {
                                      "dataBase64": "%s",
                                      "fileName": "guide.png",
                                      "contentType": "image/png"
                                    }
                                  ]
                                }
                                """.formatted(
                                GuideImportRequestContract.IMAGE_BASE64_ONE_BY_ONE_PNG)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.sourceType").value("IMAGE_OCR"))
                .andExpect(jsonPath("$.sourceHost").value("用户图片截图"))
                .andExpect(jsonPath("$.title").value("图片攻略"))
                .andExpect(jsonPath("$.normalizedDocument.sourceType").value("IMAGE_OCR"))
                .andExpect(jsonPath("$.trustedFacts[0].category").value("ADDRESS"))
                .andExpect(jsonPath("$.modelExtraction.status").value("SKIPPED"));

        mockMvc.perform(get("/api/trips/{tripId}/guide-imports", tripId)
                        .header("Authorization", bearer(token)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].sourceType").value("IMAGE_OCR"))
                .andExpect(jsonPath("$[0].trustedFacts.length()").value(1));
    }

    @Test
    void rejectsImageOcrRequestsWithoutPayloads() throws Exception {
        String token = register("guide-image-invalid-owner@example.com");
        String tripId = createTrip(token);

        mockMvc.perform(post("/api/trips/{tripId}/guide-imports", tripId)
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"sourceType": "IMAGE_OCR"}
                                """))
                .andExpect(status().isBadRequest());
    }

    @Test
    void persistsAndReturnsValidatedV13FactsWithEvidenceSpans() throws Exception {
        String token = register("trusted-fact-owner@example.com");
        String tripId = createTrip(token);

        mockMvc.perform(post("/api/trips/{tripId}/guide-imports", tripId)
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "sourceType": "TEXT_FILE",
                                  "title": "广州攻略.txt",
                                  "content": "地址：广州市荔湾区中山七路恩龙里34号。"
                                }
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.normalizedDocument.sourceType").value("TEXT_FILE"))
                .andExpect(jsonPath("$.trustedFacts[0].category").value("ADDRESS"))
                .andExpect(jsonPath("$.trustedFacts[0].evidenceStart").value(0))
                .andExpect(jsonPath("$.trustedFacts[0].evidenceEnd").value(20))
                .andExpect(jsonPath("$.trustedFacts[0].reliabilityLevel").value("COMMUNITY"))
                .andExpect(jsonPath("$.factMergeDecisions[0].selectedFactId")
                        .value("fact_00000000000000000000000000000001"))
                .andExpect(jsonPath("$.modelExtraction.status").value("SKIPPED"));

        mockMvc.perform(get("/api/trips/{tripId}/guide-imports", tripId)
                        .header("Authorization", bearer(token)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].trustedFacts.length()").value(1))
                .andExpect(jsonPath("$[0].trustedFacts[0].normalizedValue.address")
                        .value("广州市荔湾区中山七路恩龙里34号"));
    }

    @Test
    void syncsCityIntelligenceIntoTheSamePlanningEvidenceStore() throws Exception {
        String token = register("guide-city-owner@example.com");
        String tripId = createTrip(token);

        mockMvc.perform(post("/api/trips/{tripId}/guide-imports", tripId)
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "sourceType": "CITY_INTELLIGENCE",
                                  "city": "杭州",
                                  "startDate": "2030-01-01",
                                  "endDate": "2030-01-02"
                                }
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.sourceType").value("CITY_INTELLIGENCE"))
                .andExpect(jsonPath("$.title").value("广州城市实时情报"))
                .andExpect(jsonPath("$.sourceHost").value("高德城市情报"))
                .andExpect(jsonPath("$.facts[0].category").value("WEATHER"))
                .andExpect(jsonPath("$.facts[0].effectiveDate").value("2026-08-01"));
    }

    @Test
    void keepsOnlyTheLatestCityIntelligenceSnapshotEnabled() throws Exception {
        String token = register("guide-city-refresh-owner@example.com");
        String tripId = createTrip(token);
        String request = """
                {
                  "sourceType": "CITY_INTELLIGENCE",
                  "city": "广州",
                  "startDate": "2026-08-01",
                  "endDate": "2026-08-02"
                }
                """;

        for (int index = 0; index < 2; index++) {
            mockMvc.perform(post("/api/trips/{tripId}/guide-imports", tripId)
                            .header("Authorization", bearer(token))
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(request))
                    .andExpect(status().isCreated());
        }

        mockMvc.perform(get("/api/trips/{tripId}/guide-imports", tripId)
                        .header("Authorization", bearer(token)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[0].enabled").value(true))
                .andExpect(jsonPath("$[1].enabled").value(false));
    }

    @Test
    void serializesConcurrentCityIntelligenceRefreshesPerTrip() throws Exception {
        String token = register("guide-city-concurrent-owner@example.com");
        String tripId = createTrip(token, "并发城");
        String request = """
                {
                  "sourceType": "CITY_INTELLIGENCE",
                  "city": "任意客户端城市",
                  "startDate": "2030-01-01",
                  "endDate": "2030-01-02"
                }
                """;

        CompletableFuture<MvcResult> first = cityImportAsync(token, tripId, request);
        CompletableFuture<MvcResult> second = cityImportAsync(token, tripId, request);
        CompletableFuture.allOf(first, second).join();

        assertEquals(201, first.join().getResponse().getStatus());
        assertEquals(201, second.join().getResponse().getStatus());
        JsonNode imports = json(mockMvc.perform(get("/api/trips/{tripId}/guide-imports", tripId)
                        .header("Authorization", bearer(token)))
                .andExpect(status().isOk())
                .andReturn());
        long enabledCitySnapshots = imports.valueStream()
                .filter(item -> item.get("enabled").asBoolean())
                .count();
        assertEquals(1, enabledCitySnapshots);
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

    @Test
    void ownerCanDisableAndEnableAGuideSource() throws Exception {
        String ownerToken = register("guide-toggle-owner@example.com");
        String otherToken = register("guide-toggle-other@example.com");
        String tripId = createTrip(ownerToken);
        String importId = json(importGuide(ownerToken, tripId)
                .andExpect(status().isCreated())
                .andReturn()).get("id").asText();

        mockMvc.perform(put("/api/trips/{tripId}/guide-imports/{importId}", tripId, importId)
                        .header("Authorization", bearer(otherToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"enabled\": false}"))
                .andExpect(status().isNotFound());

        mockMvc.perform(put("/api/trips/{tripId}/guide-imports/{importId}", tripId, importId)
                        .header("Authorization", bearer(ownerToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"enabled\": false}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.enabled").value(false));

        mockMvc.perform(put("/api/trips/{tripId}/guide-imports/{importId}", tripId, importId)
                        .header("Authorization", bearer(ownerToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"enabled\": true}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.enabled").value(true));
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

    private CompletableFuture<MvcResult> cityImportAsync(
            String token,
            String tripId,
            String request
    ) {
        return CompletableFuture.supplyAsync(() -> {
            try {
                return mockMvc.perform(post("/api/trips/{tripId}/guide-imports", tripId)
                                .header("Authorization", bearer(token))
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(request))
                        .andReturn();
            } catch (Exception exception) {
                throw new CompletionException(exception);
            }
        });
    }

    private String createTrip(String token) throws Exception {
        return createTrip(token, "广州");
    }

    private String createTrip(String token, String destination) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "广州周末",
                                  "destination": "%s",
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
                                """.formatted(destination)))
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
            CyclicBarrier concurrentCityFetches = new CyclicBarrier(2);
            return request -> {
                boolean cityImport = request.city() != null;
                boolean imageImport =
                        !cityImport && request.images() != null && !request.images().isEmpty();
                boolean textImport =
                        request.sourceUrl() == null && !cityImport && !imageImport;
                String sourceType = request.normalizedSourceType();
                String sourceUrl = cityImport
                        ? "https://lbs.amap.com/api/webservice/guide/api/weatherinfo"
                        : textImport || imageImport
                                ? "https://user-content.trippilot.invalid/"
                                        + sourceType.replace('_', '-')
                                                .toLowerCase(java.util.Locale.ROOT)
                                        + "/test"
                                : request.sourceUrl();
                int dayOffset = fetchCounts
                        .computeIfAbsent(sourceUrl, ignored -> new AtomicInteger())
                        .getAndIncrement();
                Instant observedAt = Instant.parse("2026-07-23T08:00:00Z")
                        .plusSeconds(dayOffset * 86_400L);
                if ("并发城".equals(request.city())) {
                    try {
                        concurrentCityFetches.await();
                    } catch (Exception exception) {
                        throw new IllegalStateException(
                                "Concurrent city test barrier failed",
                                exception
                        );
                    }
                }
                String statement = sourceUrl.endsWith("/long-guide")
                        ? "景".repeat(1_000)
                        : cityImport
                                ? request.city() + "当前天气雷阵雨，31℃。"
                                : textImport
                                ? request.content()
                                : imageImport
                                ? "陈家祠地址：广州市荔湾区中山七路恩龙里34号。"
                                : "从公园前乘地铁 1 号线到陈家祠站。";
                FetchedNormalizedDocument normalizedDocument = textImport || imageImport
                        ? new FetchedNormalizedDocument(
                                "doc_00000000000000000000000000000001",
                                sourceType,
                                textImport ? "用户文本文件" : "用户图片截图",
                                sourceUrl,
                                "广州",
                                textImport ? request.title() : "图片攻略",
                                statement,
                                observedAt,
                                "b".repeat(64),
                                "utf-8",
                                "zh-CN",
                                java.util.Map.of(),
                                "COMMUNITY",
                                false
                        )
                        : null;
                List<FetchedTrustedFact> trustedFacts = textImport || imageImport
                        ? List.of(new FetchedTrustedFact(
                                "fact_00000000000000000000000000000001",
                                "doc_00000000000000000000000000000001",
                                "ADDRESS",
                                statement,
                                java.util.Map.of(
                                        "address",
                                        "广州市荔湾区中山七路恩龙里34号"
                                ),
                                statement,
                                0,
                                statement.length(),
                                0.9,
                                null,
                                observedAt,
                                observedAt.plusSeconds(90 * 86_400L),
                                sourceType,
                                "用户文本文件",
                                sourceUrl,
                                "COMMUNITY",
                                false,
                                false
                        ))
                        : List.of();
                List<FetchedMergeDecision> mergeDecisions = textImport || imageImport
                        ? List.of(new FetchedMergeDecision(
                                "fact_00000000000000000000000000000001",
                                List.of(),
                                List.of(),
                                "selected community source",
                                false
                        ))
                        : List.of();
                return new FetchedGuide(
                        sourceType,
                        sourceUrl,
                        sourceUrl,
                        cityImport ? "高德城市情报" : textImport || imageImport
                                ? textImport ? "小红书分享文本" : "用户图片截图"
                                : "example.com",
                        cityImport ? request.city() + "城市实时情报" : textImport || imageImport
                                ? textImport ? request.title() : "图片攻略"
                                : "广州周末攻略",
                        textImport || cityImport || imageImport
                                ? statement
                                : "从公园前乘地铁 1 号线到陈家祠站。",
                        cityImport
                                ? "%064x".formatted(dayOffset + 1)
                                : "a".repeat(64),
                        observedAt,
                        List.of(new FetchedFact(
                                cityImport ? "WEATHER" : textImport || imageImport
                                        ? "LOCATION" : "TRANSPORT",
                                statement,
                                statement,
                                0.84,
                                cityImport ? request.startDate() : null,
                                observedAt,
                                observedAt.plusSeconds(7 * 86_400L)
                        )),
                        normalizedDocument,
                        trustedFacts,
                        List.of(),
                        mergeDecisions,
                        new FetchedModelExtraction(
                                "SKIPPED",
                                0,
                                "MODEL_NOT_CONFIGURED",
                                "structured model provider is not configured"
                        ),
                null
                );
            };
        }
    }
}
