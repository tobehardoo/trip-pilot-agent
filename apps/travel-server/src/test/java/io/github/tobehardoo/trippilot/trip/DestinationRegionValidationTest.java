package io.github.tobehardoo.trippilot.trip;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** P2: structured destination region validation. */
class DestinationRegionValidationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    void acceptsAValidStructuredDestinationRegion() throws Exception {
        String token = register("region-ok@example.com");

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body("""
                                "destinationRegion": {
                                  "provinceCode": "440000",
                                  "provinceName": "广东省",
                                  "cityCode": "440100",
                                  "cityName": "广州",
                                  "districts": [{"districtCode": "440106", "districtName": "天河区"}]
                                }
                                """)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.destination").value("广州"))
                .andExpect(jsonPath("$.destinationRegion.provinceCode").value("440000"))
                .andExpect(jsonPath("$.destinationRegion.cityName").value("广州"))
                .andExpect(jsonPath("$.destinationRegion.districts[0].districtCode").value("440106"));
    }

    @Test
    void rejectsAForgedProvinceCode() throws Exception {
        String token = register("region-forge@example.com");

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body("""
                                "destinationRegion": {
                                  "provinceCode": "999999",
                                  "provinceName": "不存在省",
                                  "cityCode": "440100",
                                  "cityName": "广州",
                                  "districts": []
                                }
                                """)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_DESTINATION_REGION"));
    }

    @Test
    void rejectsACityThatDoesNotBelongToTheProvince() throws Exception {
        String token = register("region-city@example.com");

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body("""
                                "destinationRegion": {
                                  "provinceCode": "440000",
                                  "provinceName": "广东省",
                                  "cityCode": "110000",
                                  "cityName": "北京",
                                  "districts": []
                                }
                                """)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_DESTINATION_REGION"));
    }

    @Test
    void rejectsADistrictThatDoesNotBelongToTheCity() throws Exception {
        String token = register("region-district@example.com");

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body("""
                                "destinationRegion": {
                                  "provinceCode": "440000",
                                  "provinceName": "广东省",
                                  "cityCode": "440100",
                                  "cityName": "广州",
                                  "districts": [{"districtCode": "110101", "districtName": "东城区"}]
                                }
                                """)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_DESTINATION_REGION"));
    }

    @Test
    void allowsLegacyTripsWithoutAStructuredRegion() throws Exception {
        String token = register("region-legacy@example.com");

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body("")))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.destination").value("广州"))
                .andExpect(jsonPath("$.destinationRegion").isEmpty());
    }

    private String body(String extra) {
        return """
                {
                  "title": "长沙三日游",
                  "destination": "广州",
                  "startDate": "2026-09-01",
                  "endDate": "2026-09-03",
                  "constraints": {
                    "budgetAmount": 3000,
                    "travelers": 1,
                    "travelerType": "SOLO",
                    "pace": "BALANCED",
                    "mobilityLevel": "STANDARD",
                    "preferences": [],
                    "fixedSchedules": []
                  }%s
                }
                """.formatted(extra.isEmpty() ? "" : ",\n                  " + extra);
    }

    private String register(String email) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "email": "%s",
                                  "password": "StrongPass123!",
                                  "displayName": "Region"
                                }
                                """.formatted(email)))
                .andExpect(status().isCreated())
                .andReturn();
        JsonNode body = objectMapper.readTree(result.getResponse().getContentAsByteArray());
        return body.get("accessToken").asText();
    }

    private String bearer(String token) {
        return "Bearer " + token;
    }
}
