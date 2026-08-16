package io.github.tobehardoo.trippilot.place;

import java.util.List;

/**
 * DTOs for the owner-authenticated place search proxy (B13-D).
 *
 * Candidates are provenance data from the agent service — they carry
 * provider + estimated flags but are never verification evidence.
 *
 * B13_FIX R5 (P1-2): every candidate carries an opaque selection token
 * issued by this server.  The token is owner-scoped and TTL-bounded and
 * maps back to the canonical candidate cached server-side, so a later trip
 * save can canonicalize the ref instead of trusting client-forged fields.
 */
public final class PlaceSearchDtos {

    private PlaceSearchDtos() {
    }

    public record PlaceSearchRequest(
            String city,
            String keyword,
            Integer limit
    ) {
    }

    public record PlaceCandidate(
            String provider,
            String providerPoiId,
            String name,
            String address,
            String province,
            String city,
            String district,
            double longitude,
            double latitude,
            boolean estimated,
            // B13_FIX R5: server-issued opaque selection token.  Absent for
            // legacy agent responses (the issuance layer fills it in).
            String selectionToken
    ) {
    }

    public record PlaceSearchResponse(
            String provider,
            boolean estimated,
            List<PlaceCandidate> candidates
    ) {
    }
}
