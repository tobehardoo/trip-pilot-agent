package io.github.tobehardoo.trippilot.trip;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.trip.TripRequests.Accommodation;
import io.github.tobehardoo.trippilot.trip.TripRequests.ConstraintInput;
import io.github.tobehardoo.trippilot.trip.TripRequests.StructuredPoi;
import io.github.tobehardoo.trippilot.trip.TripRequests.TravelAnchor;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Scene-aware re-validation of structured POI anchors (P3.7): the backend
 * never trusts the client's address and coordinates. A transport category is
 * rejected for the hotel, a lodging category for arrival/departure, and a POI
 * that is missing a provider, category code, or belongs to another city fails
 * closed with a 400 instead of degrading to free text.
 */
class TripConstraintValidatorTest {

    private static final ZoneOffset CHINA = ZoneOffset.ofHours(8);
    private static final LocalDate START = LocalDate.of(2026, 8, 10);
    private static final LocalDate END = LocalDate.of(2026, 8, 12);

    private final TripConstraintValidator validator = new TripConstraintValidator();

    private static StructuredPoi poi(String city, String provider, String categoryCode) {
        return new StructuredPoi(
                "广州南站", "BV10019725", "广州市番禺区南站北路",
                new BigDecimal("113.269"), new BigDecimal("22.988"),
                city, "番禺区", provider, "高铁站", categoryCode,
                "440000", "440100", "440113"
        );
    }

    private static TravelAnchor arrival(StructuredPoi poi) {
        return new TravelAnchor("广州南站",
                OffsetDateTime.of(2026, 8, 10, 14, 0, 0, 0, CHINA), poi);
    }

    private static TravelAnchor departure(StructuredPoi poi) {
        return new TravelAnchor("广州白云机场",
                OffsetDateTime.of(2026, 8, 12, 16, 0, 0, 0, CHINA), poi);
    }

    private static Accommodation hotel(StructuredPoi poi) {
        return new Accommodation(poi.name(), poi);
    }

    private static ConstraintInput input(StructuredPoi arrivalPoi, StructuredPoi departurePoi,
                                         StructuredPoi hotelPoi) {
        TravelAnchor arrival = arrivalPoi == null ? null : arrival(arrivalPoi);
        TravelAnchor departure = departurePoi == null ? null : departure(departurePoi);
        Accommodation accommodation = hotelPoi == null ? null : hotel(hotelPoi);
        return new ConstraintInput(
                null, 2, "COUPLE", "BALANCED", List.of(), List.of(),
                arrival, departure, accommodation,
                List.of(), List.of(), null, "STANDARD"
        );
    }

    @Test
    void acceptsAValidTransportAnchor() {
        assertThatCode(() -> validator.validateContext(
                input(poi("广州市", "AMAP", "150302"), null, null), "广州", START, END))
                .doesNotThrowAnyException();
    }

    @Test
    void acceptsAValidHotelAnchor() {
        assertThatCode(() -> validator.validateContext(
                input(null, null, poi("广州市", "AMAP", "120100")), "广州", START, END))
                .doesNotThrowAnyException();
    }

    @Test
    void rejectsTransportPoiForTheHotelScene() {
        assertThatThrownBy(() -> validator.validateContext(
                input(null, null, poi("广州市", "AMAP", "150302")), "广州", START, END))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("150302 is not a valid lodging category");
    }

    @Test
    void rejectsHotelPoiForTheArrivalScene() {
        assertThatThrownBy(() -> validator.validateContext(
                input(poi("广州市", "AMAP", "120100"), null, null), "广州", START, END))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("120100 is not a valid transport category");
    }

    @Test
    void rejectsPoiWithoutAProvider() {
        assertThatThrownBy(() -> validator.validateContext(
                input(poi("广州市", null, "150302"), null, null), "广州", START, END))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("must include a provider");
    }

    @Test
    void rejectsPoiWithoutACategoryCode() {
        assertThatThrownBy(() -> validator.validateContext(
                input(poi("广州市", "AMAP", null), null, null), "广州", START, END))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("must include a category code");
    }

    @Test
    void rejectsPoiFromAnotherCity() {
        assertThatThrownBy(() -> validator.validateContext(
                input(poi("深圳市", "AMAP", "150302"), null, null), "广州", START, END))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("city must match the trip destination");
    }

    @Test
    void requiresAnchorTimesWithinTheTripDates() {
        TravelAnchor lateArrival = new TravelAnchor("广州南站",
                OffsetDateTime.of(2026, 8, 9, 14, 0, 0, 0, CHINA), poi("广州市", "AMAP", "150302"));
        ConstraintInput withLateArrival = new ConstraintInput(
                null, 2, "COUPLE", "BALANCED", List.of(), List.of(),
                lateArrival, null, null, List.of(), List.of(), null, "STANDARD"
        );
        assertThatThrownBy(() -> validator.validateContext(
                withLateArrival, "广州", START, END))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("must fall within the trip dates");
    }
}
