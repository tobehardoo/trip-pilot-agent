package io.github.tobehardoo.trippilot.planning;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("app.diagnostics")
public record InternalDiagnosticsProperties(String internalToken) {

    public InternalDiagnosticsProperties {
        if (internalToken == null || internalToken.length() < 16) {
            throw new IllegalArgumentException(
                    "app.diagnostics.internal-token must contain at least 16 characters"
            );
        }
    }
}
