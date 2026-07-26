package io.github.tobehardoo.trippilot.cityintelligence;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.transaction.annotation.Transactional;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.hamcrest.Matchers.hasSize;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@Transactional
class CitySourceRegistryFlowIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void seedsReviewedOfficialSourcesForThreePilotCities() throws Exception {
        String token = register("city-source-reader@example.com");

        mockMvc.perform(get("/api/city-sources")
                        .header("Authorization", bearer(token))
                        .param("enabled", "true")
                        .param("reviewStatus", "APPROVED"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(6))
                .andExpect(jsonPath("$[?(@.cityCode == 'CN-GD-GZ')]", hasSize(2)))
                .andExpect(jsonPath("$[?(@.cityCode == 'CN-BJ')]", hasSize(2)))
                .andExpect(jsonPath("$[?(@.cityCode == 'CN-SH')]", hasSize(2)));
    }

    @Test
    void filtersByCityAndRecordsAuditedOptimisticUpdate() throws Exception {
        String token = register("city-source-reviewer@example.com");
        MvcResult listResult = mockMvc.perform(get("/api/city-sources")
                        .header("Authorization", bearer(token))
                        .param("cityCode", "CN-BJ"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andReturn();
        JsonNode source = json(listResult).get(0);

        mockMvc.perform(put("/api/city-sources/{sourceId}", source.get("id").asText())
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "enabled": false,
                                  "reviewStatus": "REJECTED",
                                  "reviewNote": "Parser contract must be updated",
                                  "expectedVersion": %d
                                }
                                """.formatted(source.get("version").asInt())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.enabled").value(false))
                .andExpect(jsonPath("$.reviewStatus").value("REJECTED"))
                .andExpect(jsonPath("$.reviewNote").value("Parser contract must be updated"))
                .andExpect(jsonPath("$.reviewedBy").isNotEmpty())
                .andExpect(jsonPath("$.reviewedAt").isNotEmpty())
                .andExpect(jsonPath("$.version").value(source.get("version").asInt() + 1));

        mockMvc.perform(put("/api/city-sources/{sourceId}", source.get("id").asText())
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "enabled": true,
                                  "reviewStatus": "APPROVED",
                                  "expectedVersion": %d
                                }
                                """.formatted(source.get("version").asInt())))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("CITY_SOURCE_VERSION_CONFLICT"));
    }

    @Test
    void rejectsDuplicateCitySourceUrl() {
        assertThrows(
                RuntimeException.class,
                () -> jdbcTemplate.update("""
                        INSERT INTO business.city_source_registry(
                            id, city_code, city_name, source_name, source_url,
                            source_type, reliability_level, parser_strategy,
                            refresh_policy, review_status
                        )
                        SELECT gen_random_uuid(), city_code, city_name, source_name, source_url,
                               source_type, reliability_level, parser_strategy,
                               refresh_policy, review_status
                        FROM business.city_source_registry
                        LIMIT 1
                        """)
        );
    }

    private String register(String email) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "email": "%s",
                                  "password": "StrongPass123!",
                                  "displayName": "Source Reviewer"
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
}
