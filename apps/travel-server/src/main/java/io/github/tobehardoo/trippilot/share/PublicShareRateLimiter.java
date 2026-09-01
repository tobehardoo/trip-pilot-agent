package io.github.tobehardoo.trippilot.share;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;

import io.github.tobehardoo.trippilot.common.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

@Component
class PublicShareRateLimiter {

    private static final int REQUESTS_PER_MINUTE = 60;
    private static final Duration WINDOW = Duration.ofMinutes(1);

    private final Clock clock;
    private final ConcurrentHashMap<String, Window> windows = new ConcurrentHashMap<>();

    PublicShareRateLimiter(Clock clock) {
        this.clock = clock;
    }

    void check(String clientKey) {
        Instant now = clock.instant();
        Window window = windows.compute(clientKey == null ? "unknown" : clientKey, (key, current) -> {
            if (current == null || !now.isBefore(current.startedAt().plus(WINDOW))) {
                return new Window(now, 1);
            }
            return new Window(current.startedAt(), current.requests() + 1);
        });
        if (window.requests() > REQUESTS_PER_MINUTE) {
            throw new ApiException(HttpStatus.TOO_MANY_REQUESTS, "SHARE_RATE_LIMITED",
                    "Too many anonymous share requests; try again shortly");
        }
    }

    private record Window(Instant startedAt, int requests) {
    }
}
