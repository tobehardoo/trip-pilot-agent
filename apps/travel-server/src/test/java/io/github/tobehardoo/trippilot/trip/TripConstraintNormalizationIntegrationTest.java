package io.github.tobehardoo.trippilot.trip;

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

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * B1: unified effective constraint model, defaults and sources.
 *
 * Covers the normalization rules that must hold regardless of whether the
 * client sends every field:
 * <ul>
 *   <li>new trips without meal windows persist the system defaults;</li>
 *   <li>a preserved SYSTEM_DEFAULT marker stays a system default;</li>
 *   <li>explicitly supplied windows (no marker) become USER_SET;</li>
 *   <li>legacy JSONB without the new fields still reads normally;</li>
 *   <li>legacy empty meal windows are served as defaults but never backfilled;</li>
 *   <li>structured POI data round-trips and is validated.</li>
 * </ul>
 */
class TripConstraintNormalizationIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void createsTripWithoutMealWindowsAndPersistsSystemDefaults() throws Exception {
        String accessToken = registerAndGetAccessToken("defaults@example.com");
        String tripId = json(createTrip(accessToken, "").andReturn()).get("id").asText();

        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.constraints.mealWindows.length()").value(3))
                .andExpect(jsonPath("$.constraints.mealWindows[0].mealType").value("BREAKFAST"))
                .andExpect(jsonPath("$.constraints.mealWindows[0].startTime").value("08:00:00"))
                .andExpect(jsonPath("$.constraints.mealWindows[0].endTime").value("09:00:00"))
                .andExpect(jsonPath("$.constraints.mealWindows[0].source").value("SYSTEM_DEFAULT"))
                .andExpect(jsonPath("$.constraints.mealWindows[1].mealType").value("LUNCH"))
                .andExpect(jsonPath("$.constraints.mealWindows[1].startTime").value("12:00:00"))
                .andExpect(jsonPath("$.constraints.mealWindows[1].endTime").value("13:00:00"))
                .andExpect(jsonPath("$.constraints.mealWindows[1].source").value("SYSTEM_DEFAULT"))
                .andExpect(jsonPath("$.constraints.mealWindows[2].mealType").value("DINNER"))
                .andExpect(jsonPath("$.constraints.mealWindows[2].startTime").value("18:00:00"))
                .andExpect(jsonPath("$.constraints.mealWindows[2].endTime").value("19:00:00"))
                .andExpect(jsonPath("$.constraints.mealWindows[2].source").value("SYSTEM_DEFAULT"));

        // The defaults must be persisted, not merely served on read.
        String stored = jdbcTemplate.queryForObject(
                "SELECT meal_windows::text FROM business.trip_constraint WHERE trip_id = ?::uuid",
                String.class, tripId);
        org.assertj.core.api.Assertions.assertThat(stored)
                .contains("\"source\": \"SYSTEM_DEFAULT\"")
                .contains("\"mealType\": \"DINNER\"");
    }

    @Test
    void marksExplicitlySuppliedMealWindowsAsUserSet() throws Exception {
        String accessToken = registerAndGetAccessToken("user-set@example.com");
        String tripId = json(createTrip(accessToken, """
                ,
                "mealWindows": [{
                  "mealType": "LUNCH",
                  "startTime": "12:30",
                  "endTime": "13:30"
                }]
                """).andReturn()).get("id").asText();

        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.constraints.mealWindows.length()").value(1))
                .andExpect(jsonPath("$.constraints.mealWindows[0].mealType").value("LUNCH"))
                .andExpect(jsonPath("$.constraints.mealWindows[0].startTime").value("12:30:00"))
                .andExpect(jsonPath("$.constraints.mealWindows[0].source").value("USER_SET"));
    }

    @Test
    void preservesSystemDefaultSourceWhenWindowsRoundTrip() throws Exception {
        String accessToken = registerAndGetAccessToken("round-trip@example.com");
        String tripId = json(createTrip(accessToken, """
                ,
                "mealWindows": [
                  {"mealType": "BREAKFAST", "startTime": "08:00", "endTime": "09:00", "source": "SYSTEM_DEFAULT"},
                  {"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00", "source": "SYSTEM_DEFAULT"},
                  {"mealType": "DINNER", "startTime": "18:00", "endTime": "19:00", "source": "SYSTEM_DEFAULT"}
                ]
                """).andReturn()).get("id").asText();

        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.constraints.mealWindows[0].source").value("SYSTEM_DEFAULT"))
                .andExpect(jsonPath("$.constraints.mealWindows[1].source").value("SYSTEM_DEFAULT"))
                .andExpect(jsonPath("$.constraints.mealWindows[2].source").value("SYSTEM_DEFAULT"));
    }

    @Test
    void readsLegacyConstraintJsonbWithoutNewFields() throws Exception {
        String accessToken = registerAndGetAccessToken("legacy@example.com");
        UUID ownerId = ownerIdFor("legacy@example.com");
        UUID tripId = UUID.randomUUID();
        jdbcTemplate.update("""
                INSERT INTO business.trip(id, owner_id, title, destination, start_date, end_date, status, version)
                VALUES (?::uuid, ?::uuid, '旧旅行', '广州', DATE '2026-09-01', DATE '2026-09-02', 'DRAFT', 2)
                """, tripId, ownerId);
        jdbcTemplate.update("""
                INSERT INTO business.trip_constraint(
                    trip_id, budget_amount, travelers, traveler_type, pace,
                    preferences, fixed_schedules, arrival, departure, accommodation,
                    must_visit_places, avoid_places, meal_windows, mobility_level, schema_version
                ) VALUES (
                    ?::uuid, 3000, 2, 'COUPLE', 'RELAXED',
                    '[]'::jsonb, '[]'::jsonb,
                    '{"placeName":"广州南站","time":"2026-09-01T11:00:00+08:00"}'::jsonb,
                    '{"placeName":"广州白云机场","time":"2026-09-02T17:00:00+08:00"}'::jsonb,
                    '{"placeName":"老酒店"}'::jsonb,
                    '["陈家祠"]'::jsonb, '[]'::jsonb,
                    '[{"mealType":"LUNCH","startTime":"12:00","endTime":"13:00"}]'::jsonb,
                    'STANDARD', 2
                )
                """, tripId);

        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.constraints.schemaVersion").value(2))
                .andExpect(jsonPath("$.constraints.arrival.placeName").value("广州南站"))
                .andExpect(jsonPath("$.constraints.accommodation.placeName").value("老酒店"))
                .andExpect(jsonPath("$.constraints.mustVisitPlaces[0]").value("陈家祠"))
                .andExpect(jsonPath("$.constraints.mealWindows.length()").value(1))
                .andExpect(jsonPath("$.constraints.mealWindows[0].source").value("USER_SET"));
    }

    @Test
    void servesLegacyEmptyMealWindowsAsDefaultsWithoutBackfill() throws Exception {
        String accessToken = registerAndGetAccessToken("legacy-empty@example.com");
        UUID ownerId = ownerIdFor("legacy-empty@example.com");
        UUID tripId = UUID.randomUUID();
        jdbcTemplate.update("""
                INSERT INTO business.trip(id, owner_id, title, destination, start_date, end_date, status, version)
                VALUES (?::uuid, ?::uuid, '无餐窗旧旅行', '广州', DATE '2026-09-01', DATE '2026-09-03', 'DRAFT', 0)
                """, tripId, ownerId);
        jdbcTemplate.update("""
                INSERT INTO business.trip_constraint(
                    trip_id, budget_amount, travelers, traveler_type, pace,
                    preferences, fixed_schedules, must_visit_places, avoid_places,
                    meal_windows, mobility_level, schema_version
                ) VALUES (
                    ?::uuid, 3000, 1, 'SOLO', 'BALANCED',
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, 'STANDARD', 2
                )
                """, tripId);

        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.constraints.mealWindows.length()").value(3))
                .andExpect(jsonPath("$.constraints.mealWindows[0].source").value("SYSTEM_DEFAULT"))
                .andExpect(jsonPath("$.constraints.mealWindows[0].startTime").value("08:00:00"));

        // Defaults are served for display but never written back to the row.
        String stored = jdbcTemplate.queryForObject(
                "SELECT meal_windows::text FROM business.trip_constraint WHERE trip_id = ?::uuid",
                String.class, tripId);
        org.assertj.core.api.Assertions.assertThat(stored).isEqualTo("[]");
    }

    @Test
    void persistsAndReadsStructuredPoiForAccommodationAndAnchors() throws Exception {
        String accessToken = registerAndGetAccessToken("poi@example.com");
        String tripId = json(createTrip(accessToken, """
                ,
                "arrival": {
                  "placeName": "广州南站",
                  "time": "2026-09-01T11:00:00+08:00",
                  "poi": {
                    "name": "广州南站",
                    "providerPoiId": "B000A7BD2F",
                    "fullAddress": "广州市番禺区石壁街道南站北路",
                    "longitude": 113.2673,
                    "latitude": 22.9923,
                    "city": "广州市",
                    "district": "番禺区"
                  }
                },
                "departure": {
                  "placeName": "广州白云机场",
                  "time": "2026-09-02T17:00:00+08:00",
                  "poi": {
                    "name": "广州白云国际机场",
                    "providerPoiId": "B000A80Z8H",
                    "fullAddress": "广州市白云区机场路888号",
                    "longitude": 113.3047,
                    "latitude": 23.3923,
                    "city": "广州市",
                    "district": "白云区"
                  }
                },
                "accommodation": {
                  "placeName": "天河希尔顿",
                  "poi": {
                    "name": "广州天河希尔顿酒店",
                    "providerPoiId": "B0FFFABC12",
                    "fullAddress": "广州市天河区林和西横路215号",
                    "longitude": 113.3237,
                    "latitude": 23.1376,
                    "city": "广州市",
                    "district": "天河区"
                  }
                }
                """).andReturn()).get("id").asText();

        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.constraints.arrival.poi.providerPoiId").value("B000A7BD2F"))
                .andExpect(jsonPath("$.constraints.arrival.poi.city").value("广州市"))
                .andExpect(jsonPath("$.constraints.departure.poi.longitude").value(113.3047))
                .andExpect(jsonPath("$.constraints.accommodation.placeName").value("天河希尔顿"))
                .andExpect(jsonPath("$.constraints.accommodation.poi.providerPoiId").value("B0FFFABC12"))
                .andExpect(jsonPath("$.constraints.accommodation.poi.fullAddress").value("广州市天河区林和西横路215号"))
                .andExpect(jsonPath("$.constraints.accommodation.poi.latitude").value(23.1376))
                .andExpect(jsonPath("$.constraints.accommodation.poi.district").value("天河区"));
    }

    @Test
    void rejectsStructuredPoiWithUnpairedCoordinates() throws Exception {
        String accessToken = registerAndGetAccessToken("poi-invalid@example.com");

        createTrip(accessToken, """
                ,
                "accommodation": {
                  "placeName": "不完整酒店",
                  "poi": {
                    "name": "测试酒店",
                    "providerPoiId": "B0FFFABC12",
                    "longitude": 113.3237
                  }
                }
                """)
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
    }

    @Test
    void rejectsStructuredPoiWhoseCityMismatchesTheDestination() throws Exception {
        String accessToken = registerAndGetAccessToken("poi-city@example.com");

        createTrip(accessToken, """
                ,
                "accommodation": {
                  "placeName": "深圳酒店",
                  "poi": {
                    "name": "深圳湾酒店",
                    "providerPoiId": "B0FFFABC12",
                    "fullAddress": "深圳市南山区深湾一路8号",
                    "longitude": 113.9333,
                    "latitude": 22.5191,
                    "city": "深圳市",
                    "district": "南山区"
                  }
                }
                """)
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
    }

    @Test
    void writesNewJsonbAndReadsBackFully() throws Exception {
        String accessToken = registerAndGetAccessToken("full@example.com");
        String tripId = json(createTrip(accessToken, """
                ,
                "budgetAmount": 4200,
                "travelers": 3,
                "travelerType": "FAMILY",
                "pace": "RELAXED",
                "preferences": ["美食", "岭南文化"],
                "fixedSchedules": [{
                  "placeName": "广东省博物馆",
                  "startTime": "2026-09-02T10:00:00+08:00",
                  "endTime": "2026-09-02T12:00:00+08:00"
                }],
                "mustVisitPlaces": ["陈家祠"],
                "avoidPlaces": ["广州塔"],
                "mobilityLevel": "REDUCED",
                "mealWindows": [
                  {"mealType": "BREAKFAST", "startTime": "08:00", "endTime": "09:00", "source": "SYSTEM_DEFAULT"},
                  {"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00", "source": "USER_SET"},
                  {"mealType": "DINNER", "startTime": "18:00", "endTime": "19:00", "source": "SYSTEM_DEFAULT"}
                ]
                """).andReturn()).get("id").asText();

        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.constraints.schemaVersion").value(2))
                .andExpect(jsonPath("$.constraints.budgetAmount").value(4200))
                .andExpect(jsonPath("$.constraints.travelers").value(3))
                .andExpect(jsonPath("$.constraints.travelerType").value("FAMILY"))
                .andExpect(jsonPath("$.constraints.pace").value("RELAXED"))
                .andExpect(jsonPath("$.constraints.preferences.length()").value(2))
                .andExpect(jsonPath("$.constraints.fixedSchedules[0].placeName").value("广东省博物馆"))
                .andExpect(jsonPath("$.constraints.mustVisitPlaces[0]").value("陈家祠"))
                .andExpect(jsonPath("$.constraints.avoidPlaces[0]").value("广州塔"))
                .andExpect(jsonPath("$.constraints.mobilityLevel").value("REDUCED"))
                .andExpect(jsonPath("$.constraints.mealWindows[1].mealType").value("LUNCH"))
                .andExpect(jsonPath("$.constraints.mealWindows[1].source").value("USER_SET"))
                .andExpect(jsonPath("$.constraints.mealWindows[2].source").value("SYSTEM_DEFAULT"));
    }

    private org.springframework.test.web.servlet.ResultActions createTrip(
            String accessToken, String constraintBody) throws Exception {
        return mockMvc.perform(post("/api/trips")
                .header("Authorization", bearer(accessToken))
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                        {
                          "title": "广州四日慢游",
                          "destination": "广州",
                          "startDate": "2026-09-01",
                          "endDate": "2026-09-04",
                          "constraints": {
                            "budgetAmount": 6000,
                            "travelers": 2,
                            "travelerType": "FRIENDS",
                            "pace": "BALANCED",
                            "preferences": ["美食", "历史"],
                            "fixedSchedules": []
                            %s
                          }
                        }
                        """.formatted(constraintBody)));
    }

    private UUID ownerIdFor(String email) {
        return jdbcTemplate.queryForObject(
                "SELECT id FROM business.user_account WHERE email = ?",
                UUID.class, email);
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
