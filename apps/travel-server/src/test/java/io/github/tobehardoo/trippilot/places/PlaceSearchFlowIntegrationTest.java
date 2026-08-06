package io.github.tobehardoo.trippilot.places;

import java.math.BigDecimal;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * B4: authenticated, city-scoped structured place search. The AMap client is
 * replaced by a controllable stub so no real key or network is involved.
 */
class PlaceSearchFlowIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @DynamicPropertySource
    static void placeSearchProperties(DynamicPropertyRegistry registry) {
        // Non-blank key so the service calls the stub instead of reporting UNAVAILABLE.
        registry.add("app.places.amap-key", () -> "test-key");
    }

    @BeforeEach
    void resetStub() {
        StubPlaceSearchClientConfig.CLIENT.set((keyword, city, limit) -> List.of());
    }

    @TestConfiguration
    static class StubPlaceSearchClientConfig {

        static final AtomicReference<PlaceSearchClient> CLIENT = new AtomicReference<>(
                (keyword, city, limit) -> List.of()
        );

        @Bean
        @Primary
        PlaceSearchClient placeSearchClient() {
            return (keyword, city, limit) -> CLIENT.get().search(keyword, city, limit);
        }
    }

    @Test
    void returnsStructuredPoisForAuthenticatedUser() throws Exception {
        String token = registerAndGetAccessToken("places@example.com");
        StubPlaceSearchClientConfig.CLIENT.set((keyword, city, limit) -> List.of(
                new PlacePoi("长沙希尔顿酒店", "B0FFFABC12",
                        "长沙市岳麓区枫林一路123号",
                        new BigDecimal("112.9834"), new BigDecimal("28.1987"),
                        "长沙市", "岳麓区")
        ));

        mockMvc.perform(get("/api/places/search")
                        .header("Authorization", bearer(token))
                        .param("keyword", "希尔顿")
                        .param("city", "长沙"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("AVAILABLE"))
                .andExpect(jsonPath("$.results[0].name").value("长沙希尔顿酒店"))
                .andExpect(jsonPath("$.results[0].providerPoiId").value("B0FFFABC12"))
                .andExpect(jsonPath("$.results[0].longitude").value(112.9834))
                .andExpect(jsonPath("$.results[0].latitude").value(28.1987))
                .andExpect(jsonPath("$.results[0].city").value("长沙市"));
    }

    @Test
    void reportsUnavailableWhenTheProviderCannotBeReached() throws Exception {
        String token = registerAndGetAccessToken("places-down@example.com");
        StubPlaceSearchClientConfig.CLIENT.set((keyword, city, limit) -> {
            throw new PlaceSearchUnavailableException();
        });

        mockMvc.perform(get("/api/places/search")
                        .header("Authorization", bearer(token))
                        .param("keyword", "希尔顿")
                        .param("city", "长沙"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UNAVAILABLE"))
                .andExpect(jsonPath("$.results.length()").value(0));
    }

    @Test
    void rejectsOverlongKeyword() throws Exception {
        String token = registerAndGetAccessToken("places-long@example.com");

        mockMvc.perform(get("/api/places/search")
                        .header("Authorization", bearer(token))
                        .param("keyword", "汉".repeat(31))
                        .param("city", "长沙"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("PLACE_SEARCH_INVALID"));
    }

    @Test
    void requiresAuthentication() throws Exception {
        mockMvc.perform(get("/api/places/search")
                        .param("keyword", "希尔顿")
                        .param("city", "长沙"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("UNAUTHORIZED"));
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
        return objectMapper.readTree(result.getResponse().getContentAsByteArray())
                .get("accessToken").asText();
    }

    private String bearer(String accessToken) {
        return "Bearer " + accessToken;
    }
}
