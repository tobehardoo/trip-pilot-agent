package io.github.tobehardoo.trippilot.place;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceCandidate;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceSearchRequest;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceSearchResponse;
import org.junit.jupiter.api.Test;

class PlaceSuggestionServiceTest {

    private static final UUID OWNER = UUID.fromString("10000000-0000-4000-8000-000000000001");

    private static final PlaceSearchResponse DEMO_RESPONSE = new PlaceSearchResponse(
            "DEMO",
            true,
            List.of(new PlaceCandidate(
                    "DEMO", "demo-abc", "陈家祠 (demo)", "Demo location in 广州",
                    "", "广州", "", 113.2644, 23.1291, true, null))
    );

    private static final class FakeClient implements AgentPlaceSearchClient {
        int calls;

        @Override
        public PlaceSearchResponse search(PlaceSearchRequest request) {
            calls += 1;
            return DEMO_RESPONSE;
        }
    }

    @Test
    void rejectsKeywordsShorterThanTwoCharacters() {
        PlaceSuggestionService service = new PlaceSuggestionService(new FakeClient());

        assertThatThrownBy(() -> service.search(OWNER, new PlaceSearchRequest("广州", "陈", 10)))
                .isInstanceOf(ApiException.class)
                .satisfies(error -> {
                    ApiException api = (ApiException) error;
                    assertThat(api.code()).isEqualTo("VALIDATION_FAILED");
                });
    }

    @Test
    void rejectsBlankCityAndOutOfRangeLimit() {
        PlaceSuggestionService service = new PlaceSuggestionService(new FakeClient());

        assertThatThrownBy(() -> service.search(OWNER, new PlaceSearchRequest("  ", "陈家祠", 10)))
                .isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 11)))
                .isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 0)))
                .isInstanceOf(ApiException.class);
    }

    @Test
    void normalizesInputAndReturnsAgentCandidates() {
        FakeClient client = new FakeClient();
        PlaceSuggestionService service = new PlaceSuggestionService(client);

        PlaceSearchResponse response = service.search(OWNER, new PlaceSearchRequest(" 广州 ", " 陈家祠 ", 5));

        assertThat(client.calls).isEqualTo(1);
        assertThat(response.provider()).isEqualTo("DEMO");
        assertThat(response.estimated()).isTrue();
        assertThat(response.candidates()).hasSize(1);
        assertThat(response.candidates().get(0).providerPoiId()).isEqualTo("demo-abc");
    }

    @Test
    void servesIdenticalSearchesFromTheTtlCache() {
        FakeClient client = new FakeClient();
        PlaceSuggestionService service = new PlaceSuggestionService(client);

        service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10));
        service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10));
        service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10));

        assertThat(client.calls).isEqualTo(1);
    }

    @Test
    void treatsDifferentKeywordsAsDifferentCacheKeys() {
        FakeClient client = new FakeClient();
        PlaceSuggestionService service = new PlaceSuggestionService(client);

        service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10));
        service.search(OWNER, new PlaceSearchRequest("广州", "光孝寺", 10));

        assertThat(client.calls).isEqualTo(2);
    }

    // ── B13_FIX R5: selection token issuance ──────────────────────────────

    @Test
    void issuesOpaqueSelectionTokensPerCandidate() {
        FakeClient client = new FakeClient();
        PlaceSuggestionService service = new PlaceSuggestionService(client);

        PlaceSearchResponse response = service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10));

        String token = response.candidates().get(0).selectionToken();
        assertThat(token).isNotBlank();
        assertThat(token).doesNotContain("demo-abc");
    }

    @Test
    void issuedTokenRedeemsToTheCanonicalCandidateForTheOwner() {
        FakeClient client = new FakeClient();
        PlaceSelectionTokenService tokens = new PlaceSelectionTokenService();
        PlaceSuggestionService service = new PlaceSuggestionService(client, tokens);

        String token = service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10))
                .candidates().get(0).selectionToken();

        assertThat(tokens.redeem(OWNER, token))
                .isPresent()
                .hasValueSatisfying(candidate ->
                        assertThat(candidate.providerPoiId()).isEqualTo("demo-abc"));
    }

    @Test
    void tokenDoesNotRedeemForAnotherOwner() {
        FakeClient client = new FakeClient();
        PlaceSelectionTokenService tokens = new PlaceSelectionTokenService();
        PlaceSuggestionService service = new PlaceSuggestionService(client, tokens);

        String token = service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10))
                .candidates().get(0).selectionToken();

        UUID otherOwner = UUID.fromString("20000000-0000-4000-8000-000000000002");
        assertThat(tokens.redeem(otherOwner, token)).isEmpty();
    }

    @Test
    void expiredTokenDoesNotRedeem() {
        FakeClient client = new FakeClient();
        MutableClock clock = new MutableClock(Instant.parse("2026-08-01T00:00:00Z"));
        PlaceSelectionTokenService tokens = new PlaceSelectionTokenService(clock);
        PlaceSuggestionService service = new PlaceSuggestionService(client, tokens);

        String token = service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10))
                .candidates().get(0).selectionToken();
        assertThat(tokens.redeem(OWNER, token)).isPresent();

        clock.advance(Duration.ofMinutes(31));
        assertThat(tokens.redeem(OWNER, token)).isEmpty();
    }

    /** Test clock with an adjustable instant. */
    private static final class MutableClock extends Clock {
        private Instant instant;

        MutableClock(Instant instant) {
            this.instant = instant;
        }

        void advance(Duration duration) {
            this.instant = instant.plus(duration);
        }

        @Override
        public ZoneOffset getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(java.time.ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return instant;
        }
    }

    // ── B13_FIX.1 R3: structured, bounded, expiring cache keys ────────────

    private static final class DistinctClient implements AgentPlaceSearchClient {
        int calls;

        @Override
        public PlaceSearchResponse search(PlaceSearchRequest request) {
            calls += 1;
            return new PlaceSearchResponse(
                    "DEMO", true,
                    List.of(new PlaceCandidate(
                            "DEMO", "poi-" + request.keyword(), request.keyword(),
                            "Demo location in " + request.city(),
                            "", request.city(), "", 113.2644, 23.1291, true, null))
            );
        }
    }

    @Test
    void pipeCharactersDoNotCollideCacheKeys() {
        DistinctClient client = new DistinctClient();
        PlaceSuggestionService service = new PlaceSuggestionService(client);

        PlaceSearchResponse first = service.search(OWNER, new PlaceSearchRequest("广州", "AB|CD", 10));
        PlaceSearchResponse second = service.search(OWNER, new PlaceSearchRequest("广州|AB", "CD", 10));

        assertThat(client.calls).isEqualTo(2);
        assertThat(first.candidates().get(0).name()).isEqualTo("AB|CD");
        assertThat(second.candidates().get(0).name()).isEqualTo("CD");
    }

    @Test
    void identicalStructuredQueriesShareOneCacheEntry() {
        DistinctClient client = new DistinctClient();
        PlaceSuggestionService service = new PlaceSuggestionService(client);

        service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10));
        service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10));

        assertThat(client.calls).isEqualTo(1);
    }

    @Test
    void differentOwnersNeverShareCacheEntries() {
        DistinctClient client = new DistinctClient();
        PlaceSuggestionService service = new PlaceSuggestionService(client);
        UUID otherOwner = UUID.fromString("20000000-0000-4000-8000-000000000002");

        service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10));
        service.search(otherOwner, new PlaceSearchRequest("广州", "陈家祠", 10));

        assertThat(client.calls).isEqualTo(2);
    }

    @Test
    void expiredCacheEntriesTriggerAProviderCall() {
        DistinctClient client = new DistinctClient();
        MutableClock clock = new MutableClock(Instant.parse("2026-08-01T00:00:00Z"));
        PlaceSuggestionService service = new PlaceSuggestionService(client, clock);

        service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10));
        clock.advance(Duration.ofMinutes(6));
        service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10));

        assertThat(client.calls).isEqualTo(2);
    }

    @Test
    void cacheSizeNeverExceedsTheBoundedCapacity() {
        DistinctClient client = new DistinctClient();
        PlaceSuggestionService service = new PlaceSuggestionService(client);
        // capacity is 256 entries; 300 distinct queries must not grow the map.
        for (int index = 0; index < 300; index++) {
            service.search(OWNER, new PlaceSearchRequest("广州", "词" + index, 10));
        }
        assertThat(service.cacheSize()).isLessThanOrEqualTo(256);
    }

    @Test
    void concurrentIdenticalSearchesAreStable() throws Exception {
        DistinctClient client = new DistinctClient();
        PlaceSuggestionService service = new PlaceSuggestionService(client);
        java.util.concurrent.ExecutorService pool = java.util.concurrent.Executors.newFixedThreadPool(8);
        try {
            List<java.util.concurrent.Future<PlaceSearchResponse>> futures = new java.util.ArrayList<>();
            for (int index = 0; index < 32; index++) {
                futures.add(pool.submit(() ->
                        service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10))));
            }
            for (java.util.concurrent.Future<PlaceSearchResponse> future : futures) {
                assertThat(future.get().candidates().get(0).name()).isEqualTo("陈家祠");
            }
        } finally {
            pool.shutdownNow();
        }
        // Concurrent identical lookups collapse to a single provider call
        // (a small race may produce two; never one per request).
        assertThat(client.calls).isLessThanOrEqualTo(2);
    }

    // ── B13_FIX.1 R7: cross-owner probes never poison the token ────────────

    @Test
    void crossOwnerProbeDoesNotPoisonTheTokenForTheOwner() {
        FakeClient client = new FakeClient();
        PlaceSelectionTokenService tokens = new PlaceSelectionTokenService();
        PlaceSuggestionService service = new PlaceSuggestionService(client, tokens);

        String token = service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10))
                .candidates().get(0).selectionToken();
        UUID otherOwner = UUID.fromString("20000000-0000-4000-8000-000000000002");

        // B probes with A's token: rejected, but the token must survive.
        assertThat(tokens.redeem(otherOwner, token)).isEmpty();
        assertThat(tokens.redeem(otherOwner, token)).isEmpty();

        // A can still redeem afterwards.
        assertThat(tokens.redeem(OWNER, token))
                .isPresent()
                .hasValueSatisfying(candidate ->
                        assertThat(candidate.providerPoiId()).isEqualTo("demo-abc"));
    }

    @Test
    void expiredTokenRedeemRemovesAndReturnsEmpty() {
        FakeClient client = new FakeClient();
        MutableClock clock = new MutableClock(Instant.parse("2026-08-01T00:00:00Z"));
        PlaceSelectionTokenService tokens = new PlaceSelectionTokenService(clock);
        PlaceSuggestionService service = new PlaceSuggestionService(client, tokens);

        String token = service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10))
                .candidates().get(0).selectionToken();
        clock.advance(Duration.ofMinutes(31));

        assertThat(tokens.redeem(OWNER, token)).isEmpty();
        assertThat(tokens.redeem(OWNER, token)).isEmpty();
    }

    @Test
    void concurrentCrossOwnerProbesDoNotBreakLegitimateRedeem() throws Exception {
        FakeClient client = new FakeClient();
        PlaceSelectionTokenService tokens = new PlaceSelectionTokenService();
        PlaceSuggestionService service = new PlaceSuggestionService(client, tokens);

        String token = service.search(OWNER, new PlaceSearchRequest("广州", "陈家祠", 10))
                .candidates().get(0).selectionToken();
        UUID otherOwner = UUID.fromString("20000000-0000-4000-8000-000000000002");

        java.util.concurrent.ExecutorService pool = java.util.concurrent.Executors.newFixedThreadPool(8);
        try {
            List<java.util.concurrent.Future<Boolean>> futures = new java.util.ArrayList<>();
            for (int index = 0; index < 16; index++) {
                futures.add(pool.submit(() ->
                        tokens.redeem(otherOwner, token).isPresent()));
            }
            for (java.util.concurrent.Future<Boolean> future : futures) {
                assertThat(future.get()).isFalse();
            }
        } finally {
            pool.shutdownNow();
        }

        assertThat(tokens.redeem(OWNER, token)).isPresent();
    }
}
