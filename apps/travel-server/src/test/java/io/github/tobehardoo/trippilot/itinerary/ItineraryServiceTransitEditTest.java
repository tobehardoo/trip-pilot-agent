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
}
