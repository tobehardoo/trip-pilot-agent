package io.github.tobehardoo.trippilot.itinerary;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.UUID;
import org.junit.jupiter.api.Test;

class ItineraryServiceTransitEditTest {

    @Test
    void changingModeReplacesStaleRouteDataWithAnExplicitEstimate() {
        ItineraryMapper.StoredTransitLeg walking = new ItineraryMapper.StoredTransitLeg(
                UUID.randomUUID(),
                0,
                UUID.randomUUID(),
                UUID.randomUUID(),
                "WALKING",
                2_400,
                1_920,
                "AMAP",
                false,
                "[{\"longitude\":113.31,\"latitude\":23.11}]",
                false,
                java.math.BigDecimal.ZERO,
                null,
                java.time.Instant.EPOCH,
                false
        );

        ItineraryMapper.StoredTransitLeg driving = ItineraryService.applyTransitLegEdit(
                walking, "DRIVING", true
        );

        assertThat(driving.mode()).isEqualTo("DRIVING");
        assertThat(driving.durationSeconds()).isNotEqualTo(walking.durationSeconds());
        assertThat(driving.provider()).isEqualTo("DEMO");
        assertThat(driving.estimated()).isTrue();
        assertThat(driving.polylineJson()).isEqualTo("[]");
        assertThat(driving.locked()).isTrue();
    }

    @Test
    void publicTransitAndTaxiModesReceiveExplicitBackendEstimates() {
        ItineraryMapper.StoredTransitLeg walking = new ItineraryMapper.StoredTransitLeg(
                UUID.randomUUID(),
                0,
                UUID.randomUUID(),
                UUID.randomUUID(),
                "WALKING",
                5_000,
                4_020,
                "AMAP",
                false,
                "[{\"longitude\":113.31,\"latitude\":23.11}]",
                false,
                java.math.BigDecimal.ZERO,
                null,
                java.time.Instant.EPOCH,
                false
        );

        ItineraryMapper.StoredTransitLeg transit = ItineraryService.applyTransitLegEdit(
                walking, "TRANSIT", false
        );
        ItineraryMapper.StoredTransitLeg taxi = ItineraryService.applyTransitLegEdit(
                walking, "TAXI", false
        );

        assertThat(transit.mode()).isEqualTo("TRANSIT");
        assertThat(transit.durationSeconds()).isLessThan(walking.durationSeconds());
        assertThat(transit.provider()).isEqualTo("DEMO");
        assertThat(transit.estimated()).isTrue();
        assertThat(taxi.mode()).isEqualTo("TAXI");
        assertThat(taxi.durationSeconds()).isLessThan(walking.durationSeconds());
        assertThat(taxi.provider()).isEqualTo("DEMO");
        assertThat(taxi.estimated()).isTrue();
    }
}
