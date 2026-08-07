package io.github.tobehardoo.trippilot.places;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;

import io.github.tobehardoo.trippilot.common.ApiException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PlaceSearchServiceTest {

    private static final Clock CLOCK = Clock.fixed(
            Instant.parse("2026-08-06T00:00:00Z"), ZoneOffset.UTC
    );

    private FixedWindowRateLimiter rateLimiter;
    private List<String[]> recordedCalls;

    @BeforeEach
    void setUp() {
        rateLimiter = new FixedWindowRateLimiter(CLOCK);
        recordedCalls = new ArrayList<>();
    }

    private PlaceSearchService service(int rateLimit, PlaceSearchClient client) {
        return new PlaceSearchService(
                client,
                new PlaceSearchProperties("test-key", 5, 8, 30, rateLimit),
                rateLimiter
        );
    }

    private PlaceSearchClient recordingClient(List<PlacePoi> results) {
        return (keyword, city, limit) -> {
            recordedCalls.add(new String[]{keyword, city, String.valueOf(limit)});
            return results;
        };
    }

    @Test
    void returnsStructuredPoisFromTheClient() {
        PlaceSearchClient client = recordingClient(List.of(
                new PlacePoi("长沙希尔顿酒店", "B0FFFABC12",
                        "长沙市岳麓区枫林一路123号",
                        new BigDecimal("112.9834"), new BigDecimal("28.1987"),
                        "长沙市", "岳麓区", null, "经济型酒店", "120100")
        ));

        PlaceSearchResponse response = service(100, client).search("希尔顿", "长沙");

        assertThat(response.status()).isEqualTo("AVAILABLE");
        assertThat(response.results()).singleElement().satisfies(poi -> {
            assertThat(poi.name()).isEqualTo("长沙希尔顿酒店");
            assertThat(poi.providerPoiId()).isEqualTo("B0FFFABC12");
            assertThat(poi.longitude()).isEqualByComparingTo("112.9834");
            assertThat(poi.latitude()).isEqualByComparingTo("28.1987");
            assertThat(poi.city()).isEqualTo("长沙市");
        });
    }

    @Test
    void trimsAndForwardsTheKeywordAndCity() {
        PlaceSearchClient client = recordingClient(List.of());

        service(100, client).search("  希尔顿  ", "  长沙  ");

        assertThat(recordedCalls).containsExactly(new String[]{"希尔顿", "长沙", "8"});
    }

    @Test
    void rejectsKeywordLongerThanTheLimit() {
        assertThatThrownBy(() -> service(100, recordingClient(List.of())).search("汉".repeat(31), "长沙"))
                .isInstanceOf(ApiException.class)
                .satisfies(caught -> {
                    ApiException api = (ApiException) caught;
                    assertThat(api.status()).isEqualTo(HttpStatus.BAD_REQUEST);
                    assertThat(api.code()).isEqualTo("PLACE_SEARCH_INVALID");
                });
    }

    @Test
    void returnsUnavailableWhenTheKeyIsMissing() {
        PlaceSearchClient client = recordingClient(List.of());
        PlaceSearchService noKey = new PlaceSearchService(
                client, new PlaceSearchProperties("", 5, 8, 30, 100), rateLimiter);

        PlaceSearchResponse response = noKey.search("希尔顿", "长沙");

        assertThat(response.status()).isEqualTo("UNAVAILABLE");
        assertThat(response.results()).isEmpty();
        assertThat(recordedCalls).isEmpty();
    }

    @Test
    void returnsUnavailableWhenTheProviderCannotBeReached() {
        PlaceSearchClient failingClient = (keyword, city, limit) -> {
            throw new PlaceSearchUnavailableException();
        };

        PlaceSearchResponse response = service(100, failingClient).search("希尔顿", "长沙");

        assertThat(response.status()).isEqualTo("UNAVAILABLE");
        assertThat(response.results()).isEmpty();
    }

    @Test
    void rateLimitsExcessiveSearchesPerMinute() {
        PlaceSearchService limited = service(2, recordingClient(List.of()));
        limited.search("a", "长沙");
        limited.search("b", "长沙");

        assertThatThrownBy(() -> limited.search("c", "长沙"))
                .isInstanceOf(ApiException.class)
                .satisfies(caught -> {
                    ApiException api = (ApiException) caught;
                    assertThat(api.status()).isEqualTo(HttpStatus.TOO_MANY_REQUESTS);
                    assertThat(api.code()).isEqualTo("PLACE_SEARCH_RATE_LIMITED");
                });
    }
}
