package io.github.tobehardoo.trippilot.place;

import java.time.Clock;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceCandidate;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceSearchRequest;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceSearchResponse;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

/**
 * Owner-validated place search with a bounded, expiring cache (B13-D).
 *
 * Searches never write to the database; repeated identical lookups are
 * served from a small in-memory cache.
 *
 * B13_FIX R5 (P1-2): every candidate is issued an opaque owner-scoped
 * selection token, so a later trip save can canonicalize the ref instead of
 * trusting client-forgeable fields.  The cache is keyed per owner+query so
 * tokens never leak across owners.
 *
 * B13_FIX.1 R3: the cache key is an immutable structured record
 * ({@link SearchCacheKey}) — never a string concatenation — so input
 * separators like '|' cannot collide.  The cache is bounded to
 * {@link #MAX_CACHE_ENTRIES} entries with a TTL; expired entries are removed
 * on read, and stale entries are swept on insert.  No third-party cache.
 */
@Service
public class PlaceSuggestionService {

    private static final long CACHE_TTL_MILLIS = 5 * 60 * 1000L;
    private static final int MAX_LIMIT = 10;
    private static final int MAX_CACHE_ENTRIES = 256;

    private final AgentPlaceSearchClient client;
    private final PlaceSelectionTokenService tokenService;
    private final Clock clock;
    private final ConcurrentHashMap<SearchCacheKey, CacheEntry> cache = new ConcurrentHashMap<>();

    public PlaceSuggestionService(AgentPlaceSearchClient client) {
        this(client, new PlaceSelectionTokenService(), Clock.systemUTC());
    }

    /** Test seam: inject a token service (e.g. with a fixed clock). */
    @org.springframework.beans.factory.annotation.Autowired
    public PlaceSuggestionService(
            AgentPlaceSearchClient client,
            PlaceSelectionTokenService tokenService
    ) {
        this(client, tokenService, Clock.systemUTC());
    }

    /** Test seam: inject a clock for TTL/eviction tests. */
    PlaceSuggestionService(
            AgentPlaceSearchClient client,
            Clock clock
    ) {
        this(client, new PlaceSelectionTokenService(), clock);
    }

    private PlaceSuggestionService(
            AgentPlaceSearchClient client,
            PlaceSelectionTokenService tokenService,
            Clock clock
    ) {
        this.client = client;
        this.tokenService = tokenService;
        this.clock = clock;
    }

    /** Exposed for tests: the number of live cache entries. */
    int cacheSize() {
        return cache.size();
    }

    public PlaceSearchResponse search(UUID ownerId, PlaceSearchRequest request) {
        String city = request.city() == null ? "" : request.city().trim();
        String keyword = request.keyword() == null ? "" : request.keyword().trim();
        int limit = request.limit() == null ? MAX_LIMIT : request.limit();
        if (city.isEmpty() || city.length() > 120) {
            throw invalid("city must be between 1 and 120 characters");
        }
        if (keyword.length() < 2 || keyword.length() > 120) {
            throw invalid("keyword must be between 2 and 120 characters");
        }
        if (limit < 1 || limit > MAX_LIMIT) {
            throw invalid("limit must be between 1 and " + MAX_LIMIT);
        }
        SearchCacheKey key = new SearchCacheKey(ownerId, city, keyword, limit);
        long now = clock.millis();
        CacheEntry entry = cache.get(key);
        if (entry != null && entry.expiresAt() > now) {
            return entry.response();
        }
        if (entry != null) {
            // Expired entry: remove it before inserting a fresh one.
            cache.remove(key, entry);
        }
        PlaceSearchResponse response = client.search(new PlaceSearchRequest(city, keyword, limit));
        List<PlaceCandidate> candidates = response.candidates().stream()
                .map(candidate -> new PlaceCandidate(
                        candidate.provider(), candidate.providerPoiId(), candidate.name(),
                        candidate.address(), candidate.province(), candidate.city(),
                        candidate.district(), candidate.longitude(), candidate.latitude(),
                        candidate.estimated(),
                        tokenService.issue(ownerId, candidate)))
                .toList();
        PlaceSearchResponse issued = new PlaceSearchResponse(
                response.provider(), response.estimated(), candidates);
        cache.put(key, new CacheEntry(issued, now + CACHE_TTL_MILLIS));
        sweepExpired(now);
        return issued;
    }

    /**
     * Keeps the cache within {@link #MAX_CACHE_ENTRIES}: removes expired
     * entries first, then deterministically evicts the oldest remaining
     * entries when the map is still over capacity.
     */
    private void sweepExpired(long now) {
        cache.entrySet().removeIf(entry -> entry.getValue().expiresAt() <= now);
        if (cache.size() <= MAX_CACHE_ENTRIES) {
            return;
        }
        List<SearchCacheKey> oldest = cache.entrySet().stream()
                .sorted(java.util.Comparator.comparingLong(
                        entry -> entry.getValue().expiresAt()))
                .map(java.util.Map.Entry::getKey)
                .limit(cache.size() - MAX_CACHE_ENTRIES)
                .toList();
        for (SearchCacheKey key : oldest) {
            cache.remove(key);
        }
    }

    private ApiException invalid(String message) {
        return new ApiException(HttpStatus.BAD_REQUEST, "VALIDATION_FAILED", message);
    }

    /**
     * Immutable structured cache key.  Using a record (value-based equality)
     * instead of string concatenation means field boundaries are explicit and
     * input characters such as '|' can never create collisions.
     */
    private record SearchCacheKey(UUID ownerId, String city, String keyword, int limit) {
    }

    private record CacheEntry(PlaceSearchResponse response, long expiresAt) {
    }
}
