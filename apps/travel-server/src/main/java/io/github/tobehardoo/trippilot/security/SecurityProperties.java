package io.github.tobehardoo.trippilot.security;

import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("app.security")
public record SecurityProperties(
        String jwtSecret,
        Duration accessTokenTtl,
        Duration refreshTokenTtl,
        boolean refreshCookieSecure
) {
    public SecurityProperties {
        if (jwtSecret == null || jwtSecret.length() < 32) {
            throw new IllegalArgumentException("app.security.jwt-secret must contain at least 32 characters");
        }
    }
}
