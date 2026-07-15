package io.github.tobehardoo.trippilot.identity;

import java.time.Instant;
import java.util.UUID;

public record UserAccount(
        UUID id,
        String email,
        String passwordHash,
        String displayName,
        Instant createdAt
) {
}
