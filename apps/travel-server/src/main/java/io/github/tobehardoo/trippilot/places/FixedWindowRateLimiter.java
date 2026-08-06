package io.github.tobehardoo.trippilot.places;

import java.time.Clock;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

import org.springframework.stereotype.Component;

/**
 * Minimal in-memory fixed-window rate limiter. Not distributed: it bounds a
 * single server instance, which is enough to protect a low-traffic admin
 * proxy against runaway client loops.
 */
@Component
public class FixedWindowRateLimiter {

    private final Clock clock;
    private final AtomicLong windowStartSeconds = new AtomicLong(Long.MIN_VALUE);
    private final AtomicInteger used = new AtomicInteger();

    public FixedWindowRateLimiter(Clock clock) {
        this.clock = clock;
    }

    public boolean tryAcquire(int limitPerMinute) {
        long now = clock.millis() / 1000;
        long windowStart = windowStartSeconds.get();
        if (now - windowStart >= 60) {
            if (windowStartSeconds.compareAndSet(windowStart, now)) {
                used.set(0);
            }
        }
        int current = used.incrementAndGet();
        return current <= Math.max(1, limitPerMinute);
    }
}
