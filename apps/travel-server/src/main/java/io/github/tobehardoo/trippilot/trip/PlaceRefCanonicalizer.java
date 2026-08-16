package io.github.tobehardoo.trippilot.trip;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceCandidate;
import io.github.tobehardoo.trippilot.place.PlaceSelectionTokenService;
import io.github.tobehardoo.trippilot.trip.TripRequests.PlaceRefInput;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

/**
 * B13_FIX R5 (P1-2): canonicalizes PlaceRefs at trip save time.
 *
 * A ref is accepted in exactly two ways:
 *
 * <ol>
 *   <li>it carries a valid, unexpired owner-scoped selection token issued by
 *       the place-search endpoint — the server then rebuilds the ref from
 *       the cached canonical candidate, ignoring every client-forgeable
 *       field (name, address, province/city/district, coordinates);</li>
 *   <li>it carries no token but exactly matches an already-persisted ref of
 *       the same trip — an unchanged save reuses the persisted identity
 *       without a new search.</li>
 * </ol>
 *
 * Anything else is rejected with {@code PLACE_REF_TOKEN_REQUIRED} (missing)
 * or {@code PLACE_REF_TOKEN_INVALID} (forged/expired/cross-owner/mismatch).
 * The token itself never reaches persistence or the planner.
 */
@Component
public class PlaceRefCanonicalizer {

    private final PlaceSelectionTokenService tokenService;

    public PlaceRefCanonicalizer(PlaceSelectionTokenService tokenService) {
        this.tokenService = tokenService;
    }

    /**
     * Canonicalize a list of refs.  {@code persisted} are the trip's current
     * refs (empty on create); a token-free ref must equal one of them.
     *
     * B14_FIX.1 R1: {@code authoritativeCityName} is the official RegionRef
     * cityName when the trip carries a region (create/update pass it from the
     * region), falling back to the display destination only for legacy trips
     * without a region.  The display shorthand alone must never be the
     * authority — AMap returns official names like 大理白族自治州 while the
     * display destination may be 大理.
     */
    public List<PlaceRefInput> canonicalize(
            UUID ownerId,
            List<PlaceRefInput> refs,
            List<PlaceRefInput> persisted,
            String authoritativeCityName
    ) {
        List<PlaceRefInput> result = new ArrayList<>(refs.size());
        for (PlaceRefInput ref : refs) {
            result.add(canonicalizeOne(ownerId, ref, persisted, authoritativeCityName));
        }
        return List.copyOf(result);
    }

    private PlaceRefInput canonicalizeOne(
            UUID ownerId,
            PlaceRefInput ref,
            List<PlaceRefInput> persisted,
            String authoritativeCityName
    ) {
        String token = ref.selectionToken();
        if (token != null && !token.isBlank()) {
            PlaceCandidate candidate = tokenService.redeem(ownerId, token.trim())
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.BAD_REQUEST,
                            "PLACE_REF_TOKEN_INVALID",
                            "Place selection token is invalid, expired or belongs to another user"));
            if (!candidate.providerPoiId().equals(ref.providerPoiId())) {
                throw new ApiException(
                        HttpStatus.BAD_REQUEST,
                        "PLACE_REF_TOKEN_INVALID",
                        "Place selection token does not match the referenced place");
            }
            // B14_FIX.1 R1: the authoritative city is the official RegionRef
            // cityName (or the legacy destination for trips without a region).
            if (!sameCity(candidate.city(), authoritativeCityName)) {
                throw new ApiException(
                        HttpStatus.BAD_REQUEST,
                        "PLACE_REF_TOKEN_INVALID",
                        "Place selection token does not match the trip destination city");
            }
            // Canonical: server-side cached values win; the client may never
            // forge identity, names, addresses or coordinates.
            return new PlaceRefInput(
                    candidate.provider(),
                    candidate.providerPoiId(),
                    candidate.name(),
                    candidate.address(),
                    candidate.province(),
                    candidate.city(),
                    candidate.district(),
                    BigDecimal.valueOf(candidate.longitude()),
                    BigDecimal.valueOf(candidate.latitude()),
                    null
            );
        }
        for (PlaceRefInput existing : persisted) {
            if (sameRef(existing, ref)) {
                return existing;
            }
        }
        throw new ApiException(
                HttpStatus.BAD_REQUEST,
                "PLACE_REF_TOKEN_REQUIRED",
                "New or changed place refs must carry a valid selection token");
    }


    private static boolean sameCity(String candidateCity, String tripCity) {
        return normalizeCity(candidateCity).equals(normalizeCity(tripCity));
    }

    private static String normalizeCity(String value) {
        if (value == null) {
            return "";
        }
        String trimmed = value.trim();
        // B14_FIX.1 R1: only strip semantics-free administrative suffixes.
        // "自治州" is deliberately NOT stripped — 大理白族自治州 must stay
        // 大理白族自治州, never the ethnic fragment 大理白族.  The official
        // RegionRef cityName comparison already matches full official names
        // verbatim; 市/地区/盟/特别行政区 are pure suffixes with no ethnic
        // meaning, so their removal stays lossless.
        for (String suffix : new String[]{"特别行政区", "地区", "盟", "市"}) {
            if (trimmed.endsWith(suffix)) {
                trimmed = trimmed.substring(0, trimmed.length() - suffix.length());
                break;
            }
        }
        return trimmed;
    }

    private static boolean sameRef(PlaceRefInput left, PlaceRefInput right) {
        return left.provider().equals(right.provider())
                && left.providerPoiId().equals(right.providerPoiId())
                && left.name().equals(right.name())
                && left.address().equals(right.address())
                && left.province().equals(right.province())
                && left.city().equals(right.city())
                && left.district().equals(right.district())
                && left.longitude().compareTo(right.longitude()) == 0
                && left.latitude().compareTo(right.latitude()) == 0;
    }
}
