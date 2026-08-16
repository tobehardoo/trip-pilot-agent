package io.github.tobehardoo.trippilot.trip;

import java.util.Map;
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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * B13_FIX R4 (P1-1): the four municipalities (北京/上海/天津/重庆) may carry
 * provinceCode == cityCode; ordinary provinces still require the city to
 * belong to its province.
 */
class MunicipalityRegionIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void createsBeijingTripWithMunicipalityCode() throws Exception {
        String accessToken = registerAndGetAccessToken("beijing-owner@example.com");
        MvcResult result = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(regionBody(
                                "北京三日", "北京市", "北京", "110000", "110000",
                                new String[]{"110101"}, new String[]{"东城区"})))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.region.provinceCode").value("110000"))
                .andExpect(jsonPath("$.region.cityCode").value("110000"))
                .andExpect(jsonPath("$.region.districtCodes[0]").value("110101"))
                .andReturn();
        String tripId = json(result).get("id").asText();
        Map<String, Object> row = jdbcTemplate.queryForMap(
                "SELECT region_ref FROM business.trip WHERE id = ?::uuid", tripId);
        assertThat(row).containsKey("region_ref");
    }

    @Test
    void createsShanghaiTripWithMunicipalityCode() throws Exception {
        String accessToken = registerAndGetAccessToken("shanghai-owner@example.com");
        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(regionBody(
                                "上海两日", "上海市", "上海", "310000", "310000",
                                new String[]{"310101"}, new String[]{"黄浦区"})))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.region.provinceCode").value("310000"))
                .andExpect(jsonPath("$.region.cityCode").value("310000"));
    }

    @Test
    void createsTianjinTripWithMunicipalityCode() throws Exception {
        String accessToken = registerAndGetAccessToken("tianjin-owner@example.com");
        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(regionBody(
                                "天津一日", "天津市", "天津", "120000", "120000",
                                new String[]{"120101"}, new String[]{"和平区"})))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.region.provinceCode").value("120000"))
                .andExpect(jsonPath("$.region.cityCode").value("120000"));
    }

    @Test
    void createsChongqingTripWithMunicipalityCode() throws Exception {
        String accessToken = registerAndGetAccessToken("chongqing-owner@example.com");
        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(regionBody(
                                "重庆两日", "重庆市", "重庆", "500000", "500000",
                                new String[]{"500103"}, new String[]{"渝中区"})))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.region.provinceCode").value("500000"))
                .andExpect(jsonPath("$.region.cityCode").value("500000"));
    }

    @Test
    void rejectsSameCodeForOrdinaryProvince() throws Exception {
        String accessToken = registerAndGetAccessToken("fake-municipality@example.com");
        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(regionBody(
                                "伪造同码", "广东省", "广州", "440000", "440000",
                                new String[]{"440106"}, new String[]{"天河区"})))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("TRIP_REGION_INVALID"));
    }

    @Test
    void rejectsMunicipalityDistrictNotUnderItsCode() throws Exception {
        String accessToken = registerAndGetAccessToken("wrong-district@example.com");
        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(regionBody(
                                "跨区伪造", "北京市", "北京", "110000", "110000",
                                new String[]{"310101"}, new String[]{"黄浦区"})))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("TRIP_REGION_INVALID"));
    }

    private String regionBody(
            String title,
            String provinceName,
            String cityName,
            String provinceCode,
            String cityCode,
            String[] districtCodes,
            String[] districtNames
    ) {
        return """
                {
                  "title": "%s",
                  "destination": "%s / %s",
                  "region": {
                    "provinceCode": "%s",
                    "cityCode": "%s",
                    "districtCodes": %s,
                    "provinceName": "%s",
                    "cityName": "%s",
                    "districtNames": %s,
                    "datasetVersion": "2023-06-30"
                  },
                  "startDate": "2026-08-01",
                  "endDate": "2026-08-03",
                  "constraints": {
                    "travelers": 1,
                    "travelerType": "SOLO",
                    "pace": "BALANCED",
                    "preferences": [],
                    "fixedSchedules": []
                  }
                }
                """.formatted(
                title, provinceName, cityName, provinceCode, cityCode,
                arrayJson(districtCodes), provinceName, cityName, arrayJson(districtNames));
    }

    private static String arrayJson(String[] values) {
        StringBuilder builder = new StringBuilder("[");
        for (int index = 0; index < values.length; index++) {
            if (index > 0) {
                builder.append(", ");
            }
            builder.append('"').append(values[index]).append('"');
        }
        return builder.append(']').toString();
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

    private JsonNode json(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsByteArray());
    }

    private String bearer(String accessToken) {
        return "Bearer " + accessToken;
    }
}
