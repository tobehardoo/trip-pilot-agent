package io.github.tobehardoo.trippilot.userconfig;

import java.time.Instant;
import java.util.UUID;

/** 表行的原始记录（含明文 key），仅在服务内部使用。 */
public record UserApiConfigRow(
        String provider,
        String apiKey,
        String apiBaseUrl,
        String model,
        Instant updatedAt
) {
}