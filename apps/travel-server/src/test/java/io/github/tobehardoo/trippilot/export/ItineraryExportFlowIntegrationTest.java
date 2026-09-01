package io.github.tobehardoo.trippilot.export;

import java.nio.charset.StandardCharsets;
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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ItineraryExportFlowIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void exportsAnOwnedImmutableVersionAsIcsAndPdf() throws Exception {
        String token = registerAndGetAccessToken("export-owner@example.com");
        UUID tripId = createTrip(token);
        UUID versionId = seedCurrentVersionWithActivity(tripId);

        MvcResult calendar = mockMvc.perform(get("/api/trips/{tripId}/itinerary/exports/ics", tripId)
                        .header("Authorization", bearer(token))
                        .param("versionId", versionId.toString()))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Type", org.hamcrest.Matchers.containsString("text/calendar")))
                .andExpect(header().string("Content-Disposition", org.hamcrest.Matchers.containsString(".ics")))
                .andReturn();
        String ics = calendar.getResponse().getContentAsString(StandardCharsets.UTF_8);
        assertThat(ics).contains("BEGIN:VCALENDAR", "BEGIN:VEVENT", "DTSTART:20260801T010000Z",
                "LOCATION:Guangzhou Museum", "END:VCALENDAR");
        assertThat(ics).doesNotContain("DRIVING", "打车", "ROAD_TOLL");
        assertThat(ics).contains("\r\n ");
        assertThat(ics.split("\r\n"))
                .allSatisfy(physicalLine -> assertThat(physicalLine.getBytes(StandardCharsets.UTF_8))
                        .hasSizeLessThanOrEqualTo(75));

        MvcResult pdf = mockMvc.perform(get("/api/trips/{tripId}/itinerary/exports/pdf", tripId)
                        .header("Authorization", bearer(token))
                        .param("versionId", versionId.toString()))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Type", org.hamcrest.Matchers.containsString("application/pdf")))
                .andExpect(header().string("Content-Disposition", org.hamcrest.Matchers.containsString(".pdf")))
                .andReturn();
        assertThat(pdf.getResponse().getContentAsByteArray())
                .startsWith("%PDF-1.7".getBytes(StandardCharsets.US_ASCII))
                .contains("STSong-Light".getBytes(StandardCharsets.US_ASCII));
        String pdfAscii = new String(
                pdf.getResponse().getContentAsByteArray(), StandardCharsets.US_ASCII);
        assertThat(pdfAscii)
                .contains("62538F66")
                .doesNotContain("00440052004900560049004E0047")
                .doesNotContain("0036002E00350030");
    }

    @Test
    void exportsManualTaxiFareWaitAndEstimateSemanticsInThePdf() throws Exception {
        String token = registerAndGetAccessToken("export-taxi-owner@example.com");
        UUID tripId = createTrip(token);
        UUID versionId = seedCurrentVersionWithActivity(tripId);
        jdbcTemplate.update("""
                UPDATE business.transit_leg
                SET mode = 'TAXI', distance_meters = 2000, duration_seconds = 900,
                    provider = 'AMAP', estimated = true, estimated_cost = 17.20
                WHERE itinerary_day_id = (
                    SELECT id FROM business.itinerary_day
                    WHERE itinerary_version_id = ? AND day_index = 0
                )
                """, versionId);

        MvcResult pdf = mockMvc.perform(get("/api/trips/{tripId}/itinerary/exports/pdf", tripId)
                        .header("Authorization", bearer(token))
                        .param("versionId", versionId.toString()))
                .andExpect(status().isOk())
                .andReturn();

        String pdfAscii = new String(
                pdf.getResponse().getContentAsByteArray(), StandardCharsets.US_ASCII);
        assertThat(pdfAscii)
                .contains("62538F66")
                .contains("542B50198F66")
                .contains("00310037002E0032")
                .contains("FF084F307B97FF09");
    }

    private UUID seedCurrentVersionWithActivity(UUID tripId) {
        UUID itineraryId = UUID.randomUUID();
        UUID versionId = UUID.randomUUID();
        UUID dayId = UUID.randomUUID();
        UUID originId = UUID.randomUUID();
        UUID destinationId = UUID.randomUUID();
        jdbcTemplate.update("INSERT INTO business.itinerary(id, trip_id) VALUES (?, ?)", itineraryId, tripId);
        jdbcTemplate.update("""
                INSERT INTO business.itinerary_version(
                    id, itinerary_id, version_number, version_source, title,
                    estimated_total_cost, provider, constraint_snapshot
                ) VALUES (?, ?, 1, 'PLANNING_TASK', 'Export itinerary', 88, 'DEMO', '{}'::jsonb)
                """, versionId, itineraryId);
        jdbcTemplate.update("""
                INSERT INTO business.itinerary_day(id, itinerary_version_id, day_date, day_index)
                VALUES (?, ?, DATE '2026-08-01', 0)
                """, dayId, versionId);
        jdbcTemplate.update("""
                INSERT INTO business.activity(
                    id, itinerary_day_id, activity_order, title, start_time, end_time,
                    estimated_cost, source, provider_poi_id, longitude, latitude, address, locked
                ) VALUES (?, ?, 0, 'Museum visit', '2026-08-01T09:00:00+08:00',
                    '2026-08-01T10:00:00+08:00', 25, 'AMAP', 'museum-1',
                    113.2644, 23.1291,
                    'Guangzhou Museum, 123 Cultural Avenue, Yuexiu District, Guangzhou, Guangdong, China', FALSE)
                """, originId, dayId);
        jdbcTemplate.update("""
                INSERT INTO business.activity(
                    id, itinerary_day_id, activity_order, title, start_time, end_time,
                    estimated_cost, source, provider_poi_id, longitude, latitude, address, locked
                ) VALUES (?, ?, 1, 'Tower visit', '2026-08-01T10:15:00+08:00',
                    '2026-08-01T11:15:00+08:00', 25, 'AMAP', 'tower-1',
                    113.3193, 23.1091, 'Guangzhou Tower', FALSE)
                """, destinationId, dayId);
        jdbcTemplate.update("""
                INSERT INTO business.transit_leg(
                    id, itinerary_day_id, leg_order, from_activity_id, to_activity_id,
                    mode, distance_meters, duration_seconds, provider, estimated,
                    polyline, estimated_cost
                ) VALUES (?, ?, 0, ?, ?, 'DRIVING', 3200, 900, 'AMAP', FALSE,
                    '[{"longitude":113.2644,"latitude":23.1291},
                      {"longitude":113.3193,"latitude":23.1091}]'::jsonb, 6.50)
                """, UUID.randomUUID(), dayId, originId, destinationId);
        jdbcTemplate.update("UPDATE business.itinerary SET current_version_id = ? WHERE id = ?", versionId, itineraryId);
        return versionId;
    }

    private UUID createTrip(String token) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title":"Export test trip", "destination":"Guangzhou",
                                  "startDate":"2026-08-01", "endDate":"2026-08-01",
                                  "constraints":{"budgetAmount":1000,"travelers":1,
                                  "travelerType":"SOLO","pace":"BALANCED",
                                  "preferences":[],"fixedSchedules":[]}
                                }
                                """))
                .andExpect(status().isCreated())
                .andReturn();
        return UUID.fromString(json(result).get("id").asText());
    }

    private String registerAndGetAccessToken(String email) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"%s","password":"StrongPass123!","displayName":"Traveler"}
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
