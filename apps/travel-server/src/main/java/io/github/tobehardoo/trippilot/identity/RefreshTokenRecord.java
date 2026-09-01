package io.github.tobehardoo.trippilot.identity;

import java.time.Instant;
import java.util.UUID;

public record RefreshTokenRecord(
        UUID id,
        UUID userId,
        String tokenHash,
        Instant expiresAt,
        Instant revokedAt
) {
}
