package io.github.tobehardoo.trippilot.trip;

import java.util.stream.Stream;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class TripFlowIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

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
                                      "time": "2026-08-01T11:00:00+08:00"
                                    },
                                    "departure": {
                                      "placeName": "广州白云机场",
                                      "time": "2026-08-02T17:00:00+08:00"
                                    },
                                    "accommodation": {"placeName": "北京路附近酒店"},
                                    "mustVisitPlaces": ["陈家祠"],
                                    "avoidPlaces": ["广州塔"],
                                    "mealWindows": [{
                                      "mealType": "LUNCH",
                                      "startTime": "12:00",
                                      "endTime": "13:00"
                                    }],
                                    "mobilityLevel": "REDUCED"
                                  }
                                }
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.constraints.schemaVersion").value(2))
                .andExpect(jsonPath("$.constraints.arrival.placeName").value("广州南站"))
                .andExpect(jsonPath("$.constraints.departure.time")
                        .value("2026-08-02T09:00:00Z"))
                .andExpect(jsonPath("$.constraints.accommodation.placeName").value("北京路附近酒店"))
                .andExpect(jsonPath("$.constraints.mustVisitPlaces[0]").value("陈家祠"))
                .andExpect(jsonPath("$.constraints.avoidPlaces[0]").value("广州塔"))
                .andExpect(jsonPath("$.constraints.mealWindows[0].mealType").value("LUNCH"))
                .andExpect(jsonPath("$.constraints.mobilityLevel").value("REDUCED"))
                .andReturn();

        String tripId = json(result).get("id").asText();
        mockMvc.perform(get("/api/trips/{tripId}", tripId)
                        .header("Authorization", bearer(token)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.constraints.schemaVersion").value(2))
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
