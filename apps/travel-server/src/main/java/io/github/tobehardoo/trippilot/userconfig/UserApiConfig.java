package io.github.tobehardoo.trippilot.userconfig;

import java.time.Instant;

/** 用户自建的一个第三方 API 配置（天气/高德/知识库/规划）。 */
public record UserApiConfig(
        String provider,
        String apiKey,
        String apiBaseUrl,
        String model,
        Instant updatedAt
) {
}