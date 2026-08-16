package io.github.tobehardoo.trippilot.trip;

import java.util.UUID;
import java.util.stream.Stream;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceCandidate;
import io.github.tobehardoo.trippilot.place.PlaceSelectionTokenService;
import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.assertj.core.api.Assertions.assertThat;

class TripFlowIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private PlaceSelectionTokenService tokenService;

    private UUID ownerId(String email) {
        return jdbcTemplate.queryForObject(
                "SELECT id FROM business.user_account WHERE email = ?", UUID.class, email
        );
    }

    @Test
    void createsTripWithStructuredConstraintsAndReadsIt() throws Exception {
        String accessToken = registerAndGetAccessToken("owner@example.com");

        MvcResult createResult = createTrip(accessToken)
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.destination").value("广州"))
                .andExpect(jsonPath("$.version").value(0))
                .andExpect(jsonPath("$.constraints.budgetAmount").value(6000))
                .andExpect(jsonPath("$.constraints.travelerType").value("FRIENDS"))
                .andExpect(jsonPath("$.constraints.preferences[0]").value("美食"))
                .andReturn();

        String tripId = json(createResult).get("id").asText();
        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("广州四日慢游"))
                .andExpect(jsonPath("$.constraints.fixedSchedules[0].placeName").value("广州塔"));
    }

    @Test
    void createsTripWithRegionReferenceAndUsesAdcodeForPrewarm() throws Exception {
        String accessToken = registerAndGetAccessToken("region-owner@example.com");

        MvcResult createResult = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "拉萨三日游",
                                  "destination": "西藏自治区 / 拉萨市 / 城关区",
                                  "region": {
                                    "provinceCode": "540000",
                                    "cityCode": "540100",
                                    "districtCodes": ["540102"],
                                    "provinceName": "西藏自治区",
                                    "cityName": "拉萨市",
                                    "districtNames": ["城关区"],
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
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.region.provinceCode").value("540000"))
                .andExpect(jsonPath("$.region.cityCode").value("540100"))
                .andExpect(jsonPath("$.region.districtCodes[0]").value("540102"))
                .andExpect(jsonPath("$.planningCoverage").value("BASIC"))
                .andReturn();

        String tripId = json(createResult).get("id").asText();
        String cityCode = jdbcTemplate.queryForObject("""
                SELECT city_code
                FROM business.city_intelligence_refresh
                WHERE trip_id = ?::uuid
                """, String.class, tripId);
        org.assertj.core.api.Assertions.assertThat(cityCode).isEqualTo("540100");

        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.region.cityName").value("拉萨市"))
                .andExpect(jsonPath("$.region.datasetVersion").value("2023-06-30"));
    }

    @Test
    void rejectsRegionReferenceWhoseCityDoesNotBelongToProvince() throws Exception {
        String accessToken = registerAndGetAccessToken("invalid-region-owner@example.com");

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "无效区域",
                                  "destination": "广州",
                                  "region": {
                                    "provinceCode": "440000",
                                    "cityCode": "510100",
                                    "districtCodes": [],
                                    "provinceName": "广东省",
                                    "cityName": "成都市",
                                    "districtNames": [],
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
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("TRIP_REGION_INVALID"));
    }

    @Test
    void createsTripAndAtomicallyQueuesIdempotentCityIntelligencePrewarm() throws Exception {
        String accessToken = registerAndGetAccessToken("prewarm-owner@example.com");
        String tripId = json(createTrip(accessToken)
                .andExpect(status().isCreated())
                .andReturn()).get("id").asText();

        java.util.Map<String, Object> refresh = jdbcTemplate.queryForMap("""
                SELECT status, city_code, attempt_count
                FROM business.city_intelligence_refresh
                WHERE trip_id = ?::uuid
                """, tripId);
        java.util.Map<String, Object> outbox = jdbcTemplate.queryForMap("""
                SELECT event_type, routing_key, payload #>> '{payload,city}' AS city,
                       payload #>> '{payload,startDate}' AS start_date
                FROM business.outbox_event
                WHERE aggregate_id = ?::uuid
                  AND event_type = 'CITY_INTELLIGENCE_REFRESH_REQUESTED'
                """, tripId);

        org.assertj.core.api.Assertions.assertThat(refresh)
                .containsEntry("status", "QUEUED")
                .containsEntry("city_code", "CN-GD-GZ")
                .containsEntry("attempt_count", 0);
        org.assertj.core.api.Assertions.assertThat(outbox)
                .containsEntry("event_type", "CITY_INTELLIGENCE_REFRESH_REQUESTED")
                .containsEntry("routing_key", "city-intelligence.refresh")
                .containsEntry("city", "广州")
                .containsEntry("start_date", "2026-08-01");

        mockMvc.perform(get("/api/trips/{tripId}/city-intelligence", tripId)
                        .header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.tripId").value(tripId))
                .andExpect(jsonPath("$.status").value("QUEUED"))
                .andExpect(jsonPath("$.cityCode").value("CN-GD-GZ"))
                .andExpect(jsonPath("$.stale").value(true))
                .andExpect(jsonPath("$.providerDiagnostics").isArray());
    }

    @Test
    void manuallyRefreshingWithTheSameIdempotencyKeyReusesTheActiveRefresh() throws Exception {
        String accessToken = registerAndGetAccessToken("manual-refresh-owner@example.com");
        String tripId = json(createTrip(accessToken)
                .andExpect(status().isCreated())
                .andReturn()).get("id").asText();
        String idempotencyKey = "00000000-0000-4000-8000-000000000001";

        MvcResult first = mockMvc.perform(post(
                                "/api/trips/{tripId}/city-intelligence/refreshes",
                                tripId
                        )
                        .header("Authorization", bearer(accessToken))
                        .header("Idempotency-Key", idempotencyKey))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.status").value("QUEUED"))
                .andReturn();
        MvcResult second = mockMvc.perform(post(
                                "/api/trips/{tripId}/city-intelligence/refreshes",
                                tripId
                        )
                        .header("Authorization", bearer(accessToken))
                        .header("Idempotency-Key", idempotencyKey))
                .andExpect(status().isAccepted())
                .andReturn();

        org.assertj.core.api.Assertions.assertThat(json(first).get("refreshId").asText())
                .isEqualTo(json(second).get("refreshId").asText());
        Integer refreshCount = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM business.city_intelligence_refresh"
                        + " WHERE trip_id = ?::uuid",
                Integer.class,
                tripId
        );
        org.assertj.core.api.Assertions.assertThat(refreshCount).isEqualTo(1);
    }

    @Test
    void listsOnlyCurrentUsersTrips() throws Exception {
        String ownerToken = registerAndGetAccessToken("list-owner@example.com");
        String otherToken = registerAndGetAccessToken("list-other@example.com");
        createTrip(ownerToken).andExpect(status().isCreated());

        mockMvc.perform(get("/api/trips").header("Authorization", bearer(ownerToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].destination").value("广州"));
        mockMvc.perform(get("/api/trips").header("Authorization", bearer(otherToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void hidesTripsFromOtherUsers() throws Exception {
        String ownerToken = registerAndGetAccessToken("private-owner@example.com");
        String otherToken = registerAndGetAccessToken("private-other@example.com");
        String tripId = json(createTrip(ownerToken).andExpect(status().isCreated()).andReturn()).get("id").asText();

        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(otherToken)))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("TRIP_NOT_FOUND"));
    }

    @Test
    void updatesConstraintsAndRejectsStaleVersion() throws Exception {
        String accessToken = registerAndGetAccessToken("version@example.com");
        String tripId = json(createTrip(accessToken).andExpect(status().isCreated()).andReturn()).get("id").asText();
        String updateBody = """
                {
                  "version": 0,
                  "budgetAmount": 7200,
                  "travelers": 3,
                  "travelerType": "FAMILY",
                  "pace": "RELAXED",
                  "preferences": ["美食", "建筑"],
                  "fixedSchedules": []
                }
                """;

        mockMvc.perform(put("/api/trips/{tripId}/constraints", tripId)
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(updateBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.version").value(1))
                .andExpect(jsonPath("$.constraints.budgetAmount").value(7200))
                .andExpect(jsonPath("$.constraints.travelers").value(3))
                .andExpect(jsonPath("$.constraints.travelerType").value("FAMILY"))
                .andExpect(jsonPath("$.constraints.pace").value("RELAXED"))
                .andExpect(jsonPath("$.constraints.preferences[1]").value("建筑"))
                .andExpect(jsonPath("$.constraints.fixedSchedules.length()").value(0));

        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.version").value(1))
                .andExpect(jsonPath("$.constraints.budgetAmount").value(7200))
                .andExpect(jsonPath("$.constraints.travelers").value(3))
                .andExpect(jsonPath("$.constraints.travelerType").value("FAMILY"))
                .andExpect(jsonPath("$.constraints.pace").value("RELAXED"))
                .andExpect(jsonPath("$.constraints.preferences[0]").value("美食"))
                .andExpect(jsonPath("$.constraints.preferences[1]").value("建筑"))
                .andExpect(jsonPath("$.constraints.fixedSchedules.length()").value(0));

        mockMvc.perform(put("/api/trips/{tripId}/constraints", tripId)
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(updateBody))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("TRIP_VERSION_CONFLICT"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"", "\"version\": null,"})
    void rejectsConstraintUpdatesWithoutAnExplicitVersion(String versionProperty) throws Exception {
        String accessToken = registerAndGetAccessToken("missing-version@example.com");
        String tripId = json(createTrip(accessToken).andExpect(status().isCreated()).andReturn()).get("id").asText();
        String updateBody = """
                {
                  %s
                  "budgetAmount": 7200,
                  "travelers": 3,
                  "travelerType": "FAMILY",
                  "pace": "RELAXED",
                  "preferences": ["美食"],
                  "fixedSchedules": []
                }
                """.formatted(versionProperty);

        updateConstraints(accessToken, tripId, updateBody)
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
    }

    @Test
    void rejectsNullItemsInFixedSchedules() throws Exception {
        String accessToken = registerAndGetAccessToken("null-schedule@example.com");
        String tripId = json(createTrip(accessToken).andExpect(status().isCreated()).andReturn()).get("id").asText();

        updateConstraints(accessToken, tripId, """
                {
                  "version": 0,
                  "budgetAmount": 7200,
                  "travelers": 3,
                  "travelerType": "FAMILY",
                  "pace": "RELAXED",
                  "preferences": ["美食"],
                  "fixedSchedules": [null]
                }
                """)
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
    }

    @Test
    void rejectsConstraintUpdatesWithoutPace() throws Exception {
        String accessToken = registerAndGetAccessToken("missing-pace@example.com");
        String tripId = json(createTrip(accessToken).andExpect(status().isCreated()).andReturn()).get("id").asText();

        updateConstraints(accessToken, tripId, """
                {
                  "version": 0,
                  "budgetAmount": 7200,
                  "travelers": 3,
                  "travelerType": "FAMILY",
                  "preferences": ["美食"],
                  "fixedSchedules": []
                }
                """)
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"10000000000.00", "12.345"})
    void rejectsBudgetsOutsideDatabasePrecision(String budgetAmount) throws Exception {
        String accessToken = registerAndGetAccessToken("budget-precision@example.com");
        String tripId = json(createTrip(accessToken).andExpect(status().isCreated()).andReturn()).get("id").asText();
        String updateBody = """
                {
                  "version": 0,
                  "budgetAmount": %s,
                  "travelers": 3,
                  "travelerType": "FAMILY",
                  "pace": "RELAXED",
                  "preferences": ["美食"],
                  "fixedSchedules": []
                }
                """.formatted(budgetAmount);

        updateConstraints(accessToken, tripId, updateBody)
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
    }

    @Test
    void hidesConstraintUpdatesFromOtherUsers() throws Exception {
        String ownerToken = registerAndGetAccessToken("update-owner@example.com");
        String otherToken = registerAndGetAccessToken("update-other@example.com");
        String tripId = json(createTrip(ownerToken).andExpect(status().isCreated()).andReturn()).get("id").asText();

        updateConstraints(otherToken, tripId, """
                {
                  "version": 0,
                  "budgetAmount": 7200,
                  "travelers": 3,
                  "travelerType": "FAMILY",
                  "pace": "RELAXED",
                  "preferences": ["美食"],
                  "fixedSchedules": []
                }
                """)
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("TRIP_NOT_FOUND"));

        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(ownerToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.version").value(0))
                .andExpect(jsonPath("$.constraints.budgetAmount").value(6000));
    }

    @Test
    void validatesTripInputAndRequiresAuthentication() throws Exception {
        String accessToken = registerAndGetAccessToken("validation@example.com");
        String invalidBody = """
                {
                  "title": "Invalid trip",
                  "destination": "",
                  "startDate": "2026-08-05",
                  "endDate": "2026-08-01",
                  "constraints": {
                    "budgetAmount": -1,
                    "travelers": 0,
                    "preferences": [],
                    "fixedSchedules": []
                  }
                }
                """;

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(invalidBody))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));

        mockMvc.perform(get("/api/trips"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("UNAUTHORIZED"));
    }

    @ParameterizedTest
    @MethodSource("invalidCreateConstraints")
    void rejectsInvalidConstraintShapesWhenCreatingTrips(String constraints) throws Exception {
        String accessToken = registerAndGetAccessToken("create-constraint-validation@example.com");
        String body = """
                {
                  "title": "广州四日慢游",
                  "destination": "广州",
                  "startDate": "2026-08-01",
                  "endDate": "2026-08-04",
                  "constraints": {%s}
                }
                """.formatted(constraints);

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));

    }

    private static Stream<Arguments> invalidCreateConstraints() {
        return Stream.of(
                Arguments.of("""
                        "budgetAmount": 6000,
                        "travelers": 2,
                        "travelerType": "FRIENDS",
                        "preferences": [],
                        "fixedSchedules": []
                        """),
                Arguments.of("""
                        "budgetAmount": 12.345,
                        "travelers": 2,
                        "travelerType": "FRIENDS",
                        "pace": "BALANCED",
                        "preferences": [],
                        "fixedSchedules": []
                        """),
                Arguments.of("""
                        "budgetAmount": 6000,
                        "travelers": 2,
                        "travelerType": "FRIENDS",
                        "pace": "BALANCED",
                        "preferences": [],
                        "fixedSchedules": [null]
                        """));
    }

    @Test
    void createsAndReadsCompleteTravelContextV2() throws Exception {
        String token = registerAndGetAccessToken("context-v2@example.com");
        UUID ownerId = ownerId("context-v2@example.com");
        // B13_FIX.1 R2: create no longer accepts free-text anchors; every
        // non-empty place field must carry a candidate-issued PlaceRef.
        String arrivalToken = tokenService.issue(ownerId, new PlaceCandidate(
                "DEMO", "demo-arrival", "广州南站", "Demo location in 广州",
                "", "广州", "", 113.2644, 23.1291, true, null));
        String departureToken = tokenService.issue(ownerId, new PlaceCandidate(
                "DEMO", "demo-departure", "广州白云机场", "Demo location in 广州",
                "", "广州", "", 113.3090, 23.3924, true, null));
        String accommodationToken = tokenService.issue(ownerId, new PlaceCandidate(
                "DEMO", "demo-hotel", "北京路附近酒店", "Demo location in 广州",
                "", "广州", "", 113.2700, 23.1200, true, null));
        String mustVisitToken = tokenService.issue(ownerId, new PlaceCandidate(
                "DEMO", "demo-must", "陈家祠", "Demo location in 广州",
                "", "广州", "", 113.2521, 23.1267, true, null));

        MvcResult result = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "广州无障碍周末",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 2,
                                    "travelerType": "FAMILY",
                                    "pace": "RELAXED",
                                    "preferences": ["岭南文化"],
                                    "fixedSchedules": [],
                                    "arrival": {
                                      "placeName": "广州南站",
                                      "time": "2026-08-01T11:00:00+08:00",
                                      "placeRef": {
                                        "provider": "DEMO",
                                        "providerPoiId": "demo-arrival",
                                        "name": "广州南站",
                                        "address": "Demo location in 广州",
                                        "province": "",
                                        "city": "广州",
                                        "district": "",
                                        "longitude": 113.2644,
                                        "latitude": 23.1291,
                                        "selectionToken": "%s"
                                      }
                                    },
                                    "departure": {
                                      "placeName": "广州白云机场",
                                      "time": "2026-08-02T17:00:00+08:00",
                                      "placeRef": {
                                        "provider": "DEMO",
                                        "providerPoiId": "demo-departure",
                                        "name": "广州白云机场",
                                        "address": "Demo location in 广州",
                                        "province": "",
                                        "city": "广州",
                                        "district": "",
                                        "longitude": 113.3090,
                                        "latitude": 23.3924,
                                        "selectionToken": "%s"
                                      }
                                    },
                                    "accommodation": {
                                      "placeName": "北京路附近酒店",
                                      "placeRef": {
                                        "provider": "DEMO",
                                        "providerPoiId": "demo-hotel",
                                        "name": "北京路附近酒店",
                                        "address": "Demo location in 广州",
                                        "province": "",
                                        "city": "广州",
                                        "district": "",
                                        "longitude": 113.2700,
                                        "latitude": 23.1200,
                                        "selectionToken": "%s"
                                      }
                                    },
                                    "mustVisitPlaces": ["陈家祠"],
                                    "avoidPlaces": [],
                                    "mustVisitPlaceRefs": [{
                                      "provider": "DEMO",
                                      "providerPoiId": "demo-must",
                                      "name": "陈家祠",
                                      "address": "Demo location in 广州",
                                      "province": "",
                                      "city": "广州",
                                      "district": "",
                                      "longitude": 113.2521,
                                      "latitude": 23.1267,
                                      "selectionToken": "%s"
                                    }],
                                    "avoidPlaceRefs": [],
                                    "mealWindows": [{
                                      "mealType": "LUNCH",
                                      "startTime": "12:00",
                                      "endTime": "13:00"
                                    }],
                                    "mobilityLevel": "REDUCED"
                                  }
                                }
                                """.formatted(arrivalToken, departureToken, accommodationToken, mustVisitToken)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.constraints.schemaVersion").value(3))
                .andExpect(jsonPath("$.constraints.arrival.placeName").value("广州南站"))
                .andExpect(jsonPath("$.constraints.departure.time")
                        .value("2026-08-02T09:00:00Z"))
                .andExpect(jsonPath("$.constraints.accommodation.placeName").value("北京路附近酒店"))
                .andExpect(jsonPath("$.constraints.mustVisitPlaces[0]").value("陈家祠"))
                .andExpect(jsonPath("$.constraints.mustVisitPlaceRefs[0].providerPoiId").value("demo-must"))
                .andExpect(jsonPath("$.constraints.mealWindows[0].mealType").value("LUNCH"))
                .andExpect(jsonPath("$.constraints.mobilityLevel").value("REDUCED"))
                .andReturn();

        String tripId = json(result).get("id").asText();
        mockMvc.perform(get("/api/trips/{tripId}", tripId)
                        .header("Authorization", bearer(token)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.constraints.schemaVersion").value(3))
                .andExpect(jsonPath("$.constraints.mustVisitPlaces[0]").value("陈家祠"));
    }

    @Test
    void rejectsOutOfRangeTravelAnchorsAndInvalidMealWindows() throws Exception {
        String token = registerAndGetAccessToken("context-invalid@example.com");
        String base = """
                {
                  "title": "错误上下文",
                  "destination": "广州",
                  "startDate": "2026-08-01",
                  "endDate": "2026-08-02",
                  "constraints": {
                    "budgetAmount": 3000,
                    "travelers": 1,
                    "travelerType": "SOLO",
                    "pace": "BALANCED",
                    "preferences": [],
                    "fixedSchedules": [],
                    %s
                  }
                }
                """;

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(base.formatted("""
                                "arrival": {
                                  "placeName": "广州南站",
                                  "time": "2026-07-31T23:00:00+08:00"
                                }
                                """)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(base.formatted("""
                                "arrival": {
                                  "placeName": "跨时区车站",
                                  "time": "2026-08-01T01:00:00+14:00"
                                }
                                """)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(base.formatted("""
                                "fixedSchedules": [{
                                  "placeName": "跨时区安排",
                                  "startTime": "2026-08-01T01:00:00+14:00",
                                  "endTime": "2026-08-01T02:00:00+14:00"
                                }]
                                """)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(base.formatted("""
                                "mealWindows": [{
                                  "mealType": "LUNCH",
                                  "startTime": "13:00",
                                  "endTime": "12:00"
                                }]
                                """)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(base.formatted("""
                                "mealWindows": [{
                                  "mealType": "BREAKFAST",
                                  "startTime": "08:00",
                                  "endTime": "10:00"
                                }, {
                                  "mealType": "LUNCH",
                                  "startTime": "09:30",
                                  "endTime": "11:00"
                                }]
                                """)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
    }

    @Test
    void mealWindowSourceRoundTripsWithUserDefault() throws Exception {
        String token = registerAndGetAccessToken("meal-source@example.com");

        String tripId = json(mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "三餐来源",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mealWindows": [{
                                      "mealType": "LUNCH",
                                      "startTime": "12:00",
                                      "endTime": "13:00"
                                    }, {
                                      "mealType": "DINNER",
                                      "startTime": "18:00",
                                      "endTime": "19:00",
                                      "source": "DEFAULT"
                                    }, {
                                      "mealType": "BREAKFAST",
                                      "startTime": "08:00",
                                      "endTime": "09:00",
                                      "source": "DISABLED"
                                    }]
                                  }
                                }
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.constraints.mealWindows[0].source").value("USER"))
                .andExpect(jsonPath("$.constraints.mealWindows[1].source").value("DEFAULT"))
                .andExpect(jsonPath("$.constraints.mealWindows[2].source").value("DISABLED"))
                .andReturn()).get("id").asText();

        mockMvc.perform(get("/api/trips/{tripId}", tripId)
                        .header("Authorization", bearer(token)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.constraints.mealWindows[0].source").value("USER"))
                .andExpect(jsonPath("$.constraints.mealWindows[1].source").value("DEFAULT"))
                .andExpect(jsonPath("$.constraints.mealWindows[2].source").value("DISABLED"));
    }

    @Test
    void rejectsUnknownMealWindowSource() throws Exception {
        String token = registerAndGetAccessToken("meal-source-invalid@example.com");

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "非法来源",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mealWindows": [{
                                      "mealType": "LUNCH",
                                      "startTime": "12:00",
                                      "endTime": "13:00",
                                      "source": "HARD"
                                    }]
                                  }
                                }
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
    }

    @Test
    void createsTripWithStructuredPlaceRefsAndReadsThemBack() throws Exception {
        String token = registerAndGetAccessToken("place-ref-owner@example.com");
        UUID ownerId = ownerId("place-ref-owner@example.com");

        // B13_FIX R5: refs must be canonicalized from server-issued selection
        // tokens; issue one for each canned candidate the way the search
        // endpoint would.
        String mustVisitToken = tokenService.issue(ownerId, new PlaceCandidate(
                "AMAP", "B001234567", "陈家祠", "广州市荔湾区中山七路恩龙里34号",
                "广东省", "广州市", "荔湾区", 113.2405, 23.1256, false, null));
        String arrivalToken = tokenService.issue(ownerId, new PlaceCandidate(
                "DEMO", "demo-0123456789abcdef", "广州南站", "Demo location in 广州",
                "", "广州", "", 113.2644, 23.1291, true, null));

        String tripId = json(mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "结构化地点",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "arrival": {
                                      "placeName": "广州南站",
                                      "time": "2026-08-01T11:00:00+08:00",
                                      "placeRef": {
                                        "provider": "DEMO",
                                        "providerPoiId": "demo-0123456789abcdef",
                                        "name": "广州南站",
                                        "address": "Demo location in 广州",
                                        "province": "",
                                        "city": "广州",
                                        "district": "",
                                        "longitude": 113.2644,
                                        "latitude": 23.1291,
                                        "selectionToken": "%s"
                                      }
                                    },
                                    "mustVisitPlaces": ["陈家祠"],
                                    "avoidPlaces": [],
                                    "mustVisitPlaceRefs": [{
                                      "provider": "AMAP",
                                      "providerPoiId": "B001234567",
                                      "name": "陈家祠",
                                      "address": "广州市荔湾区中山七路恩龙里34号",
                                      "province": "广东省",
                                      "city": "广州市",
                                      "district": "荔湾区",
                                      "longitude": 113.2405,
                                      "latitude": 23.1256,
                                      "selectionToken": "%s"
                                    }],
                                    "avoidPlaceRefs": []
                                  }
                                }
                                """.formatted(arrivalToken, mustVisitToken)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.constraints.schemaVersion").value(3))
                .andExpect(jsonPath("$.constraints.arrival.placeRef.provider").value("DEMO"))
                .andExpect(jsonPath("$.constraints.mustVisitPlaceRefs[0].providerPoiId")
                        .value("B001234567"))
                .andExpect(jsonPath("$.constraints.mustVisitPlaceRefs[0].name").value("陈家祠"))
                .andReturn()).get("id").asText();

        mockMvc.perform(get("/api/trips/{tripId}", tripId)
                        .header("Authorization", bearer(token)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.constraints.schemaVersion").value(3))
                .andExpect(jsonPath("$.constraints.mustVisitPlaceRefs[0].provider").value("AMAP"))
                .andExpect(jsonPath("$.constraints.mustVisitPlaceRefs[0].longitude").value(113.2405))
                .andExpect(jsonPath("$.constraints.arrival.placeRef.providerPoiId")
                        .value("demo-0123456789abcdef"));
    }

    @Test
    void rejectsSelectionTokenIssuedInAnotherCity() throws Exception {
        // B14_FIX R3 (D03): a selection token issued by a search in one city
        // must never be redeemed into a trip whose destination is a different
        // city, even when every other field matches.
        String token = registerAndGetAccessToken("place-ref-cross-city@example.com");
        UUID ownerId = ownerId("place-ref-cross-city@example.com");
        // Candidate lives in 广州; the trip destination is 北京.
        String guangzhouToken = tokenService.issue(ownerId, new PlaceCandidate(
                "AMAP", "B001234567", "陈家祠", "广州市荔湾区中山七路恩龙里34号",
                "广东省", "广州市", "荔湾区", 113.2405, 23.1256, false, null));

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "跨城市令牌",
                                  "destination": "北京",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mustVisitPlaces": ["陈家祠"],
                                    "avoidPlaces": [],
                                    "mustVisitPlaceRefs": [{
                                      "provider": "AMAP",
                                      "providerPoiId": "B001234567",
                                      "name": "陈家祠",
                                      "address": "广州市荔湾区中山七路恩龙里34号",
                                      "province": "广东省",
                                      "city": "广州市",
                                      "district": "荔湾区",
                                      "longitude": 113.2405,
                                      "latitude": 23.1256,
                                      "selectionToken": "%s"
                                    }],
                                    "avoidPlaceRefs": []
                                  }
                                }
                                """.formatted(guangzhouToken)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("PLACE_REF_TOKEN_INVALID"));
    }

    @Test
    void acceptsSelectionTokenWhenCandidateCityMatchesDestinationWithoutSuffix() throws Exception {
        // B14_FIX R3 (D03): destination "广州" (no suffix) must match a
        // candidate whose city is "广州市" — normalized comparison.
        String token = registerAndGetAccessToken("place-ref-suffix-city@example.com");
        UUID ownerId = ownerId("place-ref-suffix-city@example.com");
        String guangzhouToken = tokenService.issue(ownerId, new PlaceCandidate(
                "AMAP", "B001234567", "陈家祠", "广州市荔湾区中山七路恩龙里34号",
                "广东省", "广州市", "荔湾区", 113.2405, 23.1256, false, null));

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "同城令牌",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mustVisitPlaces": ["陈家祠"],
                                    "avoidPlaces": [],
                                    "mustVisitPlaceRefs": [{
                                      "provider": "AMAP",
                                      "providerPoiId": "B001234567",
                                      "name": "陈家祠",
                                      "address": "广州市荔湾区中山七路恩龙里34号",
                                      "province": "广东省",
                                      "city": "广州市",
                                      "district": "荔湾区",
                                      "longitude": 113.2405,
                                      "latitude": 23.1256,
                                      "selectionToken": "%s"
                                    }],
                                    "avoidPlaceRefs": []
                                  }
                                }
                                """.formatted(guangzhouToken)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.constraints.mustVisitPlaceRefs[0].city").value("广州市"));
    }

    // B14_FIX.1 R1: official RegionRef.cityName is the authoritative city for
    // PlaceRef validation — the display destination shorthand ("大理") must
    // never be the sole authority when the trip carries a region.

    private static final String DALI_REGION_JSON = """
            {
              "provinceCode": "530000",
              "cityCode": "532900",
              "districtCodes": ["532901"],
              "provinceName": "云南省",
              "cityName": "大理白族自治州",
              "districtNames": ["大理市"],
              "datasetVersion": "2023-06-30"
            }
            """;

    private static final String XIANGXI_REGION_JSON = """
            {
              "provinceCode": "430000",
              "cityCode": "433100",
              "districtCodes": ["433101"],
              "provinceName": "湖南省",
              "cityName": "湘西土家族苗族自治州",
              "districtNames": ["吉首市"],
              "datasetVersion": "2023-06-30"
            }
            """;

    @Test
    void createsDaliTripWithOfficialRegionCityNameAndAutonomousPrefectureCandidate() throws Exception {
        String token = registerAndGetAccessToken("dali-region-create@example.com");
        UUID ownerId = ownerId("dali-region-create@example.com");
        String daliToken = tokenService.issue(ownerId, new PlaceCandidate(
                "AMAP", "B001234567", "大理古城", "云南省大理白族自治州大理市古城路",
                "云南省", "大理白族自治州", "大理市", 100.1595, 25.7075, false, null));

        // destination is the display shorthand; region.cityName is the official
        // name.  The candidate.city (AMap cityname) must match the official
        // name — the previous code compared against the destination shorthand
        // and wrongly rejected the legitimate same-city token.
        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "大理古城行程",
                                  "destination": "大理",
                                  "region": %s,
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mustVisitPlaces": ["大理古城"],
                                    "avoidPlaces": [],
                                    "mustVisitPlaceRefs": [{
                                      "provider": "AMAP",
                                      "providerPoiId": "B001234567",
                                      "name": "大理古城",
                                      "address": "云南省大理白族自治州大理市古城路",
                                      "province": "云南省",
                                      "city": "大理白族自治州",
                                      "district": "大理市",
                                      "longitude": 100.1595,
                                      "latitude": 25.7075,
                                      "selectionToken": "%s"
                                    }],
                                    "avoidPlaceRefs": [],
                                    "mealWindows": [],
                                    "mobilityLevel": "STANDARD"
                                  }
                                }
                                """.formatted(DALI_REGION_JSON, daliToken)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.constraints.mustVisitPlaceRefs[0].city")
                        .value("大理白族自治州"));
    }

    @Test
    void createsXiangxiTripWithOfficialRegionCityNameAndAutonomousPrefectureCandidate() throws Exception {
        String token = registerAndGetAccessToken("xiangxi-region-create@example.com");
        UUID ownerId = ownerId("xiangxi-region-create@example.com");
        String xiangxiToken = tokenService.issue(ownerId, new PlaceCandidate(
                "AMAP", "B001234567", "凤凰古城", "湖南省湘西土家族苗族自治州凤凰县",
                "湖南省", "湘西土家族苗族自治州", "凤凰县", 109.5996, 27.9483, false, null));

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "凤凰古城行程",
                                  "destination": "湘西",
                                  "region": %s,
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mustVisitPlaces": ["凤凰古城"],
                                    "avoidPlaces": [],
                                    "mustVisitPlaceRefs": [{
                                      "provider": "AMAP",
                                      "providerPoiId": "B001234567",
                                      "name": "凤凰古城",
                                      "address": "湖南省湘西土家族苗族自治州凤凰县",
                                      "province": "湖南省",
                                      "city": "湘西土家族苗族自治州",
                                      "district": "凤凰县",
                                      "longitude": 109.5996,
                                      "latitude": 27.9483,
                                      "selectionToken": "%s"
                                    }],
                                    "avoidPlaceRefs": [],
                                    "mealWindows": [],
                                    "mobilityLevel": "STANDARD"
                                  }
                                }
                                """.formatted(XIANGXI_REGION_JSON, xiangxiToken)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.constraints.mustVisitPlaceRefs[0].city")
                        .value("湘西土家族苗族自治州"));
    }

    @Test
    void updatesDaliTripConstraintsWithOfficialRegionCityName() throws Exception {
        String token = registerAndGetAccessToken("dali-region-update@example.com");
        UUID ownerId = ownerId("dali-region-update@example.com");

        MvcResult createResult = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "大理行程",
                                  "destination": "大理",
                                  "region": %s,
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mustVisitPlaces": [],
                                    "avoidPlaces": [],
                                    "mustVisitPlaceRefs": [],
                                    "avoidPlaceRefs": [],
                                    "mealWindows": [],
                                    "mobilityLevel": "STANDARD"
                                  }
                                }
                                """.formatted(DALI_REGION_JSON)))
                .andExpect(status().isCreated())
                .andReturn();
        String tripId = json(createResult).get("id").asText();

        String daliToken = tokenService.issue(ownerId, new PlaceCandidate(
                "AMAP", "B001234567", "崇圣寺三塔", "云南省大理白族自治州大理市",
                "云南省", "大理白族自治州", "大理市", 100.1458, 25.7053, false, null));

        // PUT constraints carries the same region semantics from the DB trip.
        mockMvc.perform(put("/api/trips/{tripId}/constraints", tripId)
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "version": 0,
                                  "budgetAmount": 3000,
                                  "travelers": 1,
                                  "travelerType": "SOLO",
                                  "pace": "BALANCED",
                                  "preferences": [],
                                  "fixedSchedules": [],
                                  "mustVisitPlaces": ["崇圣寺三塔"],
                                  "avoidPlaces": [],
                                  "mustVisitPlaceRefs": [{
                                    "provider": "AMAP",
                                    "providerPoiId": "B001234567",
                                    "name": "崇圣寺三塔",
                                    "address": "云南省大理白族自治州大理市",
                                    "province": "云南省",
                                    "city": "大理白族自治州",
                                    "district": "大理市",
                                    "longitude": 100.1458,
                                    "latitude": 25.7053,
                                    "selectionToken": "%s"
                                  }],
                                  "avoidPlaceRefs": [],
                                  "mealWindows": [],
                                  "mobilityLevel": "STANDARD"
                                }
                                """.formatted(daliToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.constraints.mustVisitPlaceRefs[0].city")
                        .value("大理白族自治州"));
    }

    @Test
    void anchorsAndAvoidRefsUseOfficialRegionCityName() throws Exception {
        String token = registerAndGetAccessToken("dali-region-anchors@example.com");
        UUID ownerId = ownerId("dali-region-anchors@example.com");
        String arrivalToken = tokenService.issue(ownerId, new PlaceCandidate(
                "AMAP", "B001234567", "大理站", "云南省大理白族自治州大理市",
                "云南省", "大理白族自治州", "大理市", 100.2299, 25.5952, false, null));
        String avoidToken = tokenService.issue(ownerId, new PlaceCandidate(
                "AMAP", "B009999999", "大理古城南门", "云南省大理白族自治州大理市",
                "云南省", "大理白族自治州", "大理市", 100.1741, 25.6932, false, null));

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "大理锚点行程",
                                  "destination": "大理",
                                  "region": %s,
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "arrival": {
                                      "placeName": "大理站",
                                      "time": "2026-08-01T10:00:00+08:00",
                                      "placeRef": {
                                        "provider": "AMAP",
                                        "providerPoiId": "B001234567",
                                        "name": "大理站",
                                        "address": "云南省大理白族自治州大理市",
                                        "province": "云南省",
                                        "city": "大理白族自治州",
                                        "district": "大理市",
                                        "longitude": 100.2299,
                                        "latitude": 25.5952,
                                        "selectionToken": "%s"
                                      }
                                    },
                                    "departure": null,
                                    "accommodation": null,
                                    "mustVisitPlaces": [],
                                    "avoidPlaces": ["大理古城南门"],
                                    "mustVisitPlaceRefs": [],
                                    "avoidPlaceRefs": [{
                                      "provider": "AMAP",
                                      "providerPoiId": "B009999999",
                                      "name": "大理古城南门",
                                      "address": "云南省大理白族自治州大理市",
                                      "province": "云南省",
                                      "city": "大理白族自治州",
                                      "district": "大理市",
                                      "longitude": 100.1741,
                                      "latitude": 25.6932,
                                      "selectionToken": "%s"
                                    }],
                                    "mealWindows": [],
                                    "mobilityLevel": "STANDARD"
                                  }
                                }
                                """.formatted(DALI_REGION_JSON, arrivalToken, avoidToken)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.constraints.arrival.placeRef.city")
                        .value("大理白族自治州"))
                .andExpect(jsonPath("$.constraints.avoidPlaceRefs[0].city")
                        .value("大理白族自治州"));
    }

    @Test
    void autonomousPrefectureCandidateStillRejectedForBeijingTrip() throws Exception {
        String token = registerAndGetAccessToken("dali-cross-city@example.com");
        UUID ownerId = ownerId("dali-cross-city@example.com");
        String daliToken = tokenService.issue(ownerId, new PlaceCandidate(
                "AMAP", "B001234567", "大理古城", "云南省大理白族自治州大理市古城路",
                "云南省", "大理白族自治州", "大理市", 100.1595, 25.7075, false, null));

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "跨城拒绝",
                                  "destination": "北京",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mustVisitPlaces": ["大理古城"],
                                    "avoidPlaces": [],
                                    "mustVisitPlaceRefs": [{
                                      "provider": "AMAP",
                                      "providerPoiId": "B001234567",
                                      "name": "大理古城",
                                      "address": "云南省大理白族自治州大理市古城路",
                                      "province": "云南省",
                                      "city": "大理白族自治州",
                                      "district": "大理市",
                                      "longitude": 100.1595,
                                      "latitude": 25.7075,
                                      "selectionToken": "%s"
                                    }],
                                    "avoidPlaceRefs": [],
                                    "mealWindows": [],
                                    "mobilityLevel": "STANDARD"
                                  }
                                }
                                """.formatted(daliToken)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("PLACE_REF_TOKEN_INVALID"));
    }

    @Test
    void ordinaryMunicipalityAndCityStillAcceptOfficialRegionCityName() throws Exception {
        String token = registerAndGetAccessToken("beijing-region-create@example.com");
        UUID ownerId = ownerId("beijing-region-create@example.com");
        String beijingToken = tokenService.issue(ownerId, new PlaceCandidate(
                "AMAP", "B001234567", "故宫", "北京市东城区景山前街4号",
                "北京市", "北京市", "东城区", 116.3971, 39.9172, false, null));

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "北京行程",
                                  "destination": "北京",
                                  "region": {
                                    "provinceCode": "110000",
                                    "cityCode": "110000",
                                    "districtCodes": ["110101"],
                                    "provinceName": "北京市",
                                    "cityName": "北京市",
                                    "districtNames": ["东城区"],
                                    "datasetVersion": "2023-06-30"
                                  },
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mustVisitPlaces": ["故宫"],
                                    "avoidPlaces": [],
                                    "mustVisitPlaceRefs": [{
                                      "provider": "AMAP",
                                      "providerPoiId": "B001234567",
                                      "name": "故宫",
                                      "address": "北京市东城区景山前街4号",
                                      "province": "北京市",
                                      "city": "北京市",
                                      "district": "东城区",
                                      "longitude": 116.3971,
                                      "latitude": 39.9172,
                                      "selectionToken": "%s"
                                    }],
                                    "avoidPlaceRefs": [],
                                    "mealWindows": [],
                                    "mobilityLevel": "STANDARD"
                                  }
                                }
                                """.formatted(beijingToken)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.constraints.mustVisitPlaceRefs[0].city")
                        .value("北京市"));
    }

    @Test
    void rejectsRefsWithoutSelectionTokensAndForgedTokens() throws Exception {
        String token = registerAndGetAccessToken("place-ref-forged@example.com");
        UUID ownerId = ownerId("place-ref-forged@example.com");

        // A brand-new ref without a selection token is rejected.
        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "无令牌地点",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mustVisitPlaces": ["陈家祠"],
                                    "avoidPlaces": [],
                                    "mustVisitPlaceRefs": [{
                                      "provider": "AMAP",
                                      "providerPoiId": "B001234567",
                                      "name": "陈家祠",
                                      "address": "",
                                      "province": "",
                                      "city": "",
                                      "district": "",
                                      "longitude": 113.2405,
                                      "latitude": 23.1256
                                    }],
                                    "avoidPlaceRefs": []
                                  }
                                }
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("PLACE_REF_TOKEN_REQUIRED"));

        // A forged token is rejected.
        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "伪造令牌地点",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mustVisitPlaces": ["陈家祠"],
                                    "avoidPlaces": [],
                                    "mustVisitPlaceRefs": [{
                                      "provider": "AMAP",
                                      "providerPoiId": "B001234567",
                                      "name": "陈家祠",
                                      "address": "",
                                      "province": "",
                                      "city": "",
                                      "district": "",
                                      "longitude": 113.2405,
                                      "latitude": 23.1256,
                                      "selectionToken": "forged-token"
                                    }],
                                    "avoidPlaceRefs": []
                                  }
                                }
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("PLACE_REF_TOKEN_INVALID"));

        // A token issued to another owner is rejected.
        UUID otherOwner = UUID.randomUUID();
        String otherToken = tokenService.issue(otherOwner, new PlaceCandidate(
                "AMAP", "B001234567", "陈家祠", "addr", "广东省", "广州市", "荔湾区",
                113.2405, 23.1256, false, null));
        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "跨用户令牌",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mustVisitPlaces": ["陈家祠"],
                                    "avoidPlaces": [],
                                    "mustVisitPlaceRefs": [{
                                      "provider": "AMAP",
                                      "providerPoiId": "B001234567",
                                      "name": "陈家祠",
                                      "address": "",
                                      "province": "",
                                      "city": "",
                                      "district": "",
                                      "longitude": 113.2405,
                                      "latitude": 23.1256,
                                      "selectionToken": "%s"
                                    }],
                                    "avoidPlaceRefs": []
                                  }
                                }
                                """.formatted(otherToken)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("PLACE_REF_TOKEN_INVALID"));
    }

    @Test
    void rejectsMisalignedOrInvalidPlaceRefs() throws Exception {
        String token = registerAndGetAccessToken("place-ref-invalid@example.com");
        String base = """
                {
                  "title": "错误地点引用",
                  "destination": "广州",
                  "startDate": "2026-08-01",
                  "endDate": "2026-08-02",
                  "constraints": {
                    "budgetAmount": 3000,
                    "travelers": 1,
                    "travelerType": "SOLO",
                    "pace": "BALANCED",
                    "preferences": [],
                    "fixedSchedules": [],
                    %s
                  }
                }
                """;

        // Ref name must match its parallel place name.
        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(base.formatted("""
                                "mustVisitPlaces": ["陈家祠"],
                                "mustVisitPlaceRefs": [{
                                  "provider": "AMAP",
                                  "providerPoiId": "B001234567",
                                  "name": "光孝寺",
                                  "address": "",
                                  "province": "",
                                  "city": "",
                                  "district": "",
                                  "longitude": 113.2405,
                                  "latitude": 23.1256
                                }]
                                """)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));

        // Refs must be parallel to the name list.
        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(base.formatted("""
                                "mustVisitPlaces": ["陈家祠", "光孝寺"],
                                "mustVisitPlaceRefs": [{
                                  "provider": "AMAP",
                                  "providerPoiId": "B001234567",
                                  "name": "陈家祠",
                                  "address": "",
                                  "province": "",
                                  "city": "",
                                  "district": "",
                                  "longitude": 113.2405,
                                  "latitude": 23.1256
                                }]
                                """)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));

        // Unknown provider whitelist entry is rejected.
        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(base.formatted("""
                                "mustVisitPlaces": ["陈家祠"],
                                "mustVisitPlaceRefs": [{
                                  "provider": "GOOGLE",
                                  "providerPoiId": "B001234567",
                                  "name": "陈家祠",
                                  "address": "",
                                  "province": "",
                                  "city": "",
                                  "district": "",
                                  "longitude": 113.2405,
                                  "latitude": 23.1256
                                }]
                                """)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
    }

    @Test
    void rejectsTripsLongerThanSevenDays() throws Exception {
        String token = registerAndGetAccessToken("bounded-trip@example.com");

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "超长旅行",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-08",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": []
                                  }
                                }
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
    }

    // ── B13-C: optional title, deterministic default, version-aware rename ──

    @Test
    void createsTripWithGeneratedDefaultTitleWhenTitleIsMissing() throws Exception {
        String accessToken = registerAndGetAccessToken("default-title@example.com");

        MvcResult createResult = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "destination": "广州",
                                  "startDate": "2026-08-20",
                                  "endDate": "2026-08-21",
                                  "constraints": {
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": []
                                  }
                                }
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.title").value("2026年08月20日—08月21日 广州市旅行规划"))
                .andReturn();

        String tripId = json(createResult).get("id").asText();
        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(accessToken)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("2026年08月20日—08月21日 广州市旅行规划"));
    }

    @Test
    void renamesTripThroughVersionAwareMetadataUpdate() throws Exception {
        String accessToken = registerAndGetAccessToken("rename@example.com");
        String tripId = json(createTrip(accessToken).andExpect(status().isCreated()).andReturn())
                .get("id").asText();

        mockMvc.perform(put("/api/trips/{tripId}/metadata", tripId)
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "expectedVersion": 0, "title": "国庆广州行" }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("国庆广州行"))
                .andExpect(jsonPath("$.version").value(1));

        // Stale version fails closed with 409.
        mockMvc.perform(put("/api/trips/{tripId}/metadata", tripId)
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "expectedVersion": 0, "title": "过期改名" }
                                """))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("TRIP_VERSION_CONFLICT"));

        // Blank title regenerates the deterministic default, never an empty string.
        mockMvc.perform(put("/api/trips/{tripId}/metadata", tripId)
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "expectedVersion": 1, "title": "" }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("2026年08月01日—08月04日 广州市旅行规划"));
    }

    @Test
    void metadataRenameIsOwnerScoped() throws Exception {
        String ownerToken = registerAndGetAccessToken("rename-owner@example.com");
        String otherToken = registerAndGetAccessToken("rename-other@example.com");
        String tripId = json(createTrip(ownerToken).andExpect(status().isCreated()).andReturn())
                .get("id").asText();

        mockMvc.perform(put("/api/trips/{tripId}/metadata", tripId)
                        .header("Authorization", bearer(otherToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "expectedVersion": 0, "title": "越权改名" }
                                """))
                .andExpect(status().isNotFound());
    }

    // ── B13-E: datetime boundaries ─────────────────────────────────────────

    @Test
    void createsTripWithDatetimeBoundariesAndProjectsDatesInChina() throws Exception {
        String accessToken = registerAndGetAccessToken("datetime-boundary@example.com");

        MvcResult createResult = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "destination": "广州",
                                  "arrivalAt": "2026-08-20T09:00:00+08:00",
                                  "departureAt": "2026-08-21T18:00:00+08:00",
                                  "constraints": {
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": []
                                  }
                                }
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.startDate").value("2026-08-20"))
                .andExpect(jsonPath("$.endDate").value("2026-08-21"))
                .andExpect(jsonPath("$.arrivalAt").value("2026-08-20T01:00:00Z"))
                .andExpect(jsonPath("$.departureAt").value("2026-08-21T10:00:00Z"))
                .andExpect(jsonPath("$.title").value("2026年08月20日—08月21日 广州市旅行规划"))
                .andReturn();

        String tripId = json(createResult).get("id").asText();
        assertThat(jdbcTemplate.queryForMap("""
                SELECT start_date, end_date, arrival_at, departure_at
                FROM business.trip WHERE id = ?::uuid
                """, tripId))
                .containsEntry("start_date", java.sql.Date.valueOf("2026-08-20"))
                .containsEntry("end_date", java.sql.Date.valueOf("2026-08-21"))
                .containsEntry("arrival_at", java.sql.Timestamp.from(
                        java.time.OffsetDateTime.parse("2026-08-20T09:00:00+08:00").toInstant()))
                .containsEntry("departure_at", java.sql.Timestamp.from(
                        java.time.OffsetDateTime.parse("2026-08-21T18:00:00+08:00").toInstant()));
    }

    @Test
    void projectsUtcDatetimesOntoChinaDates() throws Exception {
        String accessToken = registerAndGetAccessToken("utc-boundary@example.com");
        // 2026-08-20T20:00:00Z is already 2026-08-21 04:00 in Asia/Shanghai.
        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "destination": "广州",
                                  "arrivalAt": "2026-08-20T20:00:00Z",
                                  "departureAt": "2026-08-22T20:00:00Z",
                                  "constraints": {
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": []
                                  }
                                }
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.startDate").value("2026-08-21"))
                .andExpect(jsonPath("$.endDate").value("2026-08-23"));
    }

    @Test
    void rejectsPartialOrReversedDatetimeBoundaries() throws Exception {
        String accessToken = registerAndGetAccessToken("invalid-boundary@example.com");

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "destination": "广州",
                                  "arrivalAt": "2026-08-20T09:00:00+08:00",
                                  "constraints": {
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": []
                                  }
                                }
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("TRIP_BOUNDARIES_INVALID"));

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(accessToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "destination": "广州",
                                  "arrivalAt": "2026-08-21T09:00:00+08:00",
                                  "departureAt": "2026-08-20T09:00:00+08:00",
                                  "constraints": {
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": []
                                  }
                                }
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("TRIP_BOUNDARIES_INVALID"));
    }

    @Test
    void legacyDateOnlyCreateStillWorksAndDoesNotFabricateTimes() throws Exception {
        String accessToken = registerAndGetAccessToken("legacy-dates@example.com");

        MvcResult createResult = createTrip(accessToken)
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.arrivalAt").value(org.hamcrest.Matchers.nullValue()))
                .andExpect(jsonPath("$.departureAt").value(org.hamcrest.Matchers.nullValue()))
                .andReturn();

        String tripId = json(createResult).get("id").asText();
        assertThat(jdbcTemplate.queryForObject(
                "SELECT arrival_at IS NULL AND departure_at IS NULL FROM business.trip WHERE id = ?::uuid",
                Boolean.class, tripId)).isTrue();
    }

    private org.springframework.test.web.servlet.ResultActions createTrip(String accessToken) throws Exception {
        return mockMvc.perform(post("/api/trips")
                .header("Authorization", bearer(accessToken))
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                        {
                          "title": "广州四日慢游",
                          "destination": "广州",
                          "startDate": "2026-08-01",
                          "endDate": "2026-08-04",
                          "constraints": {
                            "budgetAmount": 6000,
                            "travelers": 2,
                            "travelerType": "FRIENDS",
                            "pace": "BALANCED",
                            "preferences": ["美食", "历史"],
                            "fixedSchedules": [{
                              "placeName": "广州塔",
                              "startTime": "2026-08-02T19:00:00+08:00",
                              "endTime": "2026-08-02T21:00:00+08:00"
                            }]
                          }
                        }
                        """));
    }

    private org.springframework.test.web.servlet.ResultActions updateConstraints(
            String accessToken, String tripId, String body) throws Exception {
        return mockMvc.perform(put("/api/trips/{tripId}/constraints", tripId)
                .header("Authorization", bearer(accessToken))
                .contentType(MediaType.APPLICATION_JSON)
                .content(body));
    }

    // ── B13_FIX.1 R2: free-text anchors require a selected candidate ───────

    @Test
    void createRejectsFreeTextAnchorWithoutPlaceRef() throws Exception {
        String token = registerAndGetAccessToken("r2-create-free-text@example.com");

        mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "自由文本到达",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "arrival": {
                                      "placeName": "随便输入的车站名XYZ",
                                      "time": "2026-08-01T11:00:00+08:00"
                                    }
                                  }
                                }
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("PLACE_REF_REQUIRED"));
    }

    @Test
    void updateRejectsNewFreeTextAnchorWithoutPlaceRef() throws Exception {
        String token = registerAndGetAccessToken("r2-update-new@example.com");
        String tripId = createLegacyTrip(token);

        updateConstraints(token, tripId, """
                {
                  "version": 0,
                  "budgetAmount": 3000,
                  "travelers": 1,
                  "travelerType": "SOLO",
                  "pace": "BALANCED",
                  "preferences": [],
                  "fixedSchedules": [],
                  "arrival": {
                    "placeName": "新输入的自由文本",
                    "time": "2026-08-01T11:00:00+08:00"
                  },
                  "mustVisitPlaces": [],
                  "avoidPlaces": [],
                  "mealWindows": [],
                  "mobilityLevel": "STANDARD"
                }
                """)
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("PLACE_REF_REQUIRED"));
    }

    @Test
    void updateRejectsChangedLegacyAnchorWithoutPlaceRef() throws Exception {
        String token = registerAndGetAccessToken("r2-update-changed@example.com");
        String tripId = createLegacyTrip(token);

        updateConstraints(token, tripId, """
                {
                  "version": 0,
                  "budgetAmount": 3000,
                  "travelers": 1,
                  "travelerType": "SOLO",
                  "pace": "BALANCED",
                  "preferences": [],
                  "fixedSchedules": [],
                  "arrival": {
                    "placeName": "被改过的旧站名",
                    "time": "2026-08-01T11:00:00+08:00"
                  },
                  "mustVisitPlaces": [],
                  "avoidPlaces": [],
                  "mealWindows": [],
                  "mobilityLevel": "STANDARD"
                }
                """)
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("PLACE_REF_REQUIRED"));
    }

    @Test
    void updateKeepsUnchangedLegacyAnchor() throws Exception {
        String token = registerAndGetAccessToken("r2-update-legacy@example.com");
        String tripId = createLegacyTrip(token);

        updateConstraints(token, tripId, """
                {
                  "version": 0,
                  "budgetAmount": 3000,
                  "travelers": 1,
                  "travelerType": "SOLO",
                  "pace": "BALANCED",
                  "preferences": [],
                  "fixedSchedules": [],
                  "arrival": {
                    "placeName": "广州南站",
                    "time": "2026-08-01T11:00:00+08:00"
                  },
                  "mustVisitPlaces": [],
                  "avoidPlaces": [],
                  "mealWindows": [],
                  "mobilityLevel": "STANDARD"
                }
                """)
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.constraints.arrival.placeName").value("广州南站"));
    }

    @Test
    void updateRejectsChangedStructuredAnchorWithoutNewToken() throws Exception {
        String token = registerAndGetAccessToken("r2-update-struct@example.com");
        UUID ownerId = ownerId("r2-update-struct@example.com");
        String arrivalToken = tokenService.issue(ownerId, new PlaceCandidate(
                "DEMO", "demo-0123456789abcdef", "广州南站", "Demo location in 广州",
                "", "广州", "", 113.2644, 23.1291, true, null));
        String tripId = json(mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "结构化到达",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "arrival": {
                                      "placeName": "广州南站",
                                      "time": "2026-08-01T11:00:00+08:00",
                                      "placeRef": {
                                        "provider": "DEMO",
                                        "providerPoiId": "demo-0123456789abcdef",
                                        "name": "广州南站",
                                        "address": "Demo location in 广州",
                                        "province": "",
                                        "city": "广州",
                                        "district": "",
                                        "longitude": 113.2644,
                                        "latitude": 23.1291,
                                        "selectionToken": "%s"
                                      }
                                    },
                                    "mustVisitPlaces": [],
                                    "avoidPlaces": []
                                  }
                                }
                                """.formatted(arrivalToken)))
                        .andExpect(status().isCreated())
                        .andReturn()).get("id").asText();

        // The structured ref is changed (new text, no new token) → 400.
        updateConstraints(token, tripId, """
                {
                  "version": 1,
                  "budgetAmount": 3000,
                  "travelers": 1,
                  "travelerType": "SOLO",
                  "pace": "BALANCED",
                  "preferences": [],
                  "fixedSchedules": [],
                  "arrival": {
                    "placeName": "改名后的南站",
                    "time": "2026-08-01T11:00:00+08:00"
                  },
                  "mustVisitPlaces": [],
                  "avoidPlaces": [],
                  "mealWindows": [],
                  "mobilityLevel": "STANDARD"
                }
                """)
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("PLACE_REF_REQUIRED"));
    }

    private String createLegacyTrip(String token) throws Exception {
        String tripId = json(mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "旧式行程",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mustVisitPlaces": [],
                                    "avoidPlaces": []
                                  }
                                }
                                """))
                        .andExpect(status().isCreated())
                        .andReturn()).get("id").asText();
        // Simulate a pre-B13 legacy row: an arrival anchor persisted as
        // free text without any PlaceRef (the create endpoint no longer
        // accepts this, so it is injected directly into the database).
        jdbcTemplate.update("""
                UPDATE business.trip_constraint
                SET arrival = CAST(? AS jsonb)
                WHERE trip_id = ?
                """, """
                {"placeName": "广州南站", "time": "2026-08-01T11:00:00+08:00"}
                """, java.util.UUID.fromString(tripId));
        return tripId;
    }


    @Test
    void hidesItineraryVersionsFromUsersWhoDoNotOwnTheTrip() throws Exception {
        String ownerToken = registerAndGetAccessToken("version-owner@example.com");
        String otherToken = registerAndGetAccessToken("version-other@example.com");
        String tripId = json(mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(ownerToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "版本隔离",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-02",
                                  "arrivalAt": "2026-08-01T10:00:00+08:00",
                                  "departureAt": "2026-08-02T18:00:00+08:00",
                                  "constraints": {
                                    "budgetAmount": 3000,
                                    "travelers": 1,
                                    "travelerType": "SOLO",
                                    "pace": "BALANCED",
                                    "preferences": [],
                                    "fixedSchedules": [],
                                    "mustVisitPlaces": [],
                                    "avoidPlaces": [],
                                    "mustVisitPlaceRefs": [],
                                    "avoidPlaceRefs": [],
                                    "mealWindows": [],
                                    "mobilityLevel": "STANDARD"
                                  }
                                }
                                """))
                .andExpect(status().isCreated())
                .andReturn()).get("id").asText();

        // RED: the owner can list versions (possibly empty)...
        mockMvc.perform(get("/api/trips/{tripId}/itinerary/versions", tripId)
                        .header("Authorization", bearer(ownerToken)))
                .andExpect(status().isOk());

        // ...but a non-owner must receive the same 404 as a missing trip —
        // never 200 + empty list, which leaks that the trip id exists.
        mockMvc.perform(get("/api/trips/{tripId}/itinerary/versions", tripId)
                        .header("Authorization", bearer(otherToken)))
                .andExpect(status().isNotFound());

        // A trip that does not exist is a uniform 404 for everyone.
        mockMvc.perform(get("/api/trips/{tripId}/itinerary/versions", UUID.randomUUID())
                        .header("Authorization", bearer(ownerToken)))
                .andExpect(status().isNotFound());
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
