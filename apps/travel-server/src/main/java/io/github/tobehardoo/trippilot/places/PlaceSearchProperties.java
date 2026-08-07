package io.github.tobehardoo.trippilot.places;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Server-only AMap Web Service search configuration. The key never leaves the server. */
@ConfigurationProperties("app.places")
public record PlaceSearchProperties(
        String amapKey,
        int amapTimeoutSeconds,
        int maxResults,
        int keywordMaxLength,
        int rateLimitPerMinute
) {
}
