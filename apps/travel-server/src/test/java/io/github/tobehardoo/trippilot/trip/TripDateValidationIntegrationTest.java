package io.github.tobehardoo.trippilot.trip;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.concurrent.atomic.AtomicReference;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * B3: Beijing-time date validation for new trips.
 *
 * "Today" is the server date in Asia/Shanghai, injected via a mutable fixed
 * clock so each scenario can pin the reference instant. The client's browser
 * time zone is irrelevant: a UTC instant that is already the next calendar day
 * in Beijing counts as that later date.
 */
class TripDateValidationIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private org.springframework.jdbc.core.JdbcTemplate jdbcTemplate;

    @TestConfiguration
    static class FixedClockConfig {

        static final AtomicReference<Instant> NOW = new AtomicReference<>(
                Instant.parse("2026-08-05T20:00:00Z") // Beijing 2026-08-06 04:00
        );

        @Bean
        @Primary
        Clock fixedClock() {
            return new Clock() {
                @Override
                public ZoneId getZone() {
                    return ZoneOffset.UTC;
                }

                @Override
                public Clock withZone(ZoneId zone) {
                    return Clock.fixed(NOW.get(), zone);
                }

                @Override
                public Instant instant() {
                    return NOW.get();
                }
            };
        }
    }

    @Test
    void systemTimeReportsBeijingTodayWithoutAuthentication() throws Exception {
        FixedClockConfig.NOW.set(Instant.parse("2026-08-05T20:00:00Z"));
        mockMvc.perform(get("/api/system/time"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.serverDate").value("2026-08-06"))
                .andExpect(jsonPath("$.timeZone").value("Asia/Shanghai"));
    }

    @Test
    void createsTripStartingToday() throws Exception {
        FixedClockConfig.NOW.set(Instant.parse("2026-08-05T20:00:00Z"));
        String token = registerAndGetAccessToken("today@example.com");

        createTrip(token, "2026-08-06", "2026-08-08")
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.startDate").value("2026-08-06"));
    }

    @Test
    void rejectsTripStartingYesterday() throws Exception {
        FixedClockConfig.NOW.set(Instant.parse("2026-08-05T20:00:00Z"));
        String token = registerAndGetAccessToken("past@example.com");

        createTrip(token, "2026-08-05", "2026-08-08")
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("TRIP_START_DATE_IN_PAST"));
    }

    @Test
    void rejectsPastDateAcrossNewYearBoundary() throws Exception {
        // Beijing is already 2027-01-01 while UTC is still 2026-12-31.
        FixedClockConfig.NOW.set(Instant.parse("2026-12-31T16:00:00Z"));
        String token = registerAndGetAccessToken("newyear@example.com");

        createTrip(token, "2026-12-31", "2027-01-02")
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("TRIP_START_DATE_IN_PAST"));

        createTrip(token, "2027-01-01", "2027-01-03")
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.startDate").value("2027-01-01"));
    }

    @Test
    void beijingDateDiffersFromUtcDateAroundMidnight() throws Exception {
        // UTC is still 08-05, but Beijing has already rolled to 08-06, so a
        // trip "starting 08-05" is in the past. A naive client anchored to UTC
        // would be fooled; the server must not be.
        FixedClockConfig.NOW.set(Instant.parse("2026-08-05T20:00:00Z"));
        String token = registerAndGetAccessToken("midnight@example.com");

        createTrip(token, "2026-08-05", "2026-08-07")
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("TRIP_START_DATE_IN_PAST"));
    }

    @Test
    void rejectsEndDateBeforeStartDate() throws Exception {
        FixedClockConfig.NOW.set(Instant.parse("2026-08-05T20:00:00Z"));
        String token = registerAndGetAccessToken("range@example.com");

        createTrip(token, "2026-08-07", "2026-08-06")
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
    }

    @Test
    void readingHistoricalTripIsUnaffectedByPastDateValidation() throws Exception {
        // A trip created before the rule took effect (started in the past) is
        // still readable; only creation rejects past dates.
        FixedClockConfig.NOW.set(Instant.parse("2026-08-05T20:00:00Z"));
        String token = registerAndGetAccessToken("historical@example.com");
        String tripId = json(createTrip(token, "2026-08-06", "2026-08-08")
                .andExpect(status().isCreated()).andReturn()).get("id").asText();

        // Back-date the stored trip directly to simulate a historical record.
        jdbcTemplate.update("""
                UPDATE business.trip SET start_date = DATE '2026-07-01', end_date = DATE '2026-07-03'
                WHERE id = ?::uuid
                """, tripId);

        mockMvc.perform(get("/api/trips/{tripId}", tripId).header("Authorization", bearer(token)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.startDate").value("2026-07-01"));
    }

    private org.springframework.test.web.servlet.ResultActions createTrip(
            String token, String startDate, String endDate) throws Exception {
        return mockMvc.perform(post("/api/trips")
                .header("Authorization", bearer(token))
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                        {
                          "title": "长沙三日游",
                          "destination": "长沙",
                          "startDate": "%s",
                          "endDate": "%s",
                          "constraints": {
                            "budgetAmount": 3000,
                            "travelers": 2,
                            "travelerType": "COUPLE",
                            "pace": "BALANCED",
                            "preferences": ["美食"],
                            "fixedSchedules": []
                          }
                        }
                        """.formatted(startDate, endDate)));
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
