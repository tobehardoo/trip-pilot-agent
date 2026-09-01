package io.github.tobehardoo.trippilot.place;

import java.security.SecureRandom;
import java.time.Clock;
import java.util.Base64;
import java.util.Iterator;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceCandidate;
import org.springframework.stereotype.Component;

/**
 * B13_FIX R5 (P1-2): server-issued, owner-scoped, bounded-TTL selection
 * tokens for place-search candidates.
 *
 * Every candidate returned by {@code POST /api/trips/places/search} carries
 * an opaque token.  The token maps back to the canonical candidate cached
 * here, so a later trip save can canonicalize the ref instead of trusting
 * client-forgeable fields (name, address, coordinates).  Tokens are bound
 * to the searching owner, expire after {@link #TTL_MILLIS}, and the cache is
 * capacity-bounded with lazy expiry eviction — a small local single-instance
 * design, no persistence, no clocks beyond the injected {@link Clock}.
 */
@Component
public class PlaceSelectionTokenService {

    private static final long TTL_MILLIS = 30 * 60 * 1000L;
    private static final int MAX_ENTRIES = 256;
    private static final SecureRandom RANDOM = new SecureRandom();

    private final ConcurrentHashMap<String, TokenEntry> tokens = new ConcurrentHashMap<>();
    private final Clock clock;

    public PlaceSelectionTokenService() {
        this(Clock.systemUTC());
    }

    /** Test seam: inject a fixed clock. */
    public PlaceSelectionTokenService(Clock clock) {
        this.clock = clock;
    }

    /** Issue a fresh opaque token for one candidate, scoped to the owner. */
    public String issue(UUID ownerId, PlaceCandidate candidate) {
        evictExpired();
        String token = randomToken();
        tokens.put(token, new TokenEntry(ownerId, candidate, clock.millis() + TTL_MILLIS));
        if (tokens.size() > MAX_ENTRIES) {
            evictExpired();
        }
        while (tokens.size() > MAX_ENTRIES) {
            evictOldest();
        }
        return token;
    }

    /** Redeem a token; returns the canonical candidate only for the owner. */
    public Optional<PlaceCandidate> redeem(UUID ownerId, String token) {
        TokenEntry entry = tokens.get(token);
        if (entry == null) {
            return Optional.empty();
        }
        if (entry.expiresAt() <= clock.millis()) {
            // Expired tokens are removed so the map stays bounded.
            tokens.remove(token, entry);
            return Optional.empty();
        }
        if (!entry.ownerId().equals(ownerId)) {
            // B13_FIX.1 R7: a cross-owner probe must never poison the token —
            // the legitimate owner can still redeem it afterwards.
            return Optional.empty();
        }
        return Optional.of(entry.candidate());
    }

    private String randomToken() {
        byte[] bytes = new byte[24];
        RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private void evictExpired() {
        long now = clock.millis();
        Iterator<Map.Entry<String, TokenEntry>> iterator = tokens.entrySet().iterator();
        while (iterator.hasNext()) {
            TokenEntry entry = iterator.next().getValue();
            if (entry.expiresAt() <= now) {
                iterator.remove();
            }
        }
    }

    private void evictOldest() {
        String oldestKey = null;
        long oldestExpiry = Long.MAX_VALUE;
        for (Map.Entry<String, TokenEntry> entry : tokens.entrySet()) {
            if (entry.getValue().expiresAt() < oldestExpiry) {
                oldestExpiry = entry.getValue().expiresAt();
                oldestKey = entry.getKey();
            }
        }
        if (oldestKey != null) {
            tokens.remove(oldestKey);
        }
    }

    private record TokenEntry(UUID ownerId, PlaceCandidate candidate, long expiresAt) {
    }
}
