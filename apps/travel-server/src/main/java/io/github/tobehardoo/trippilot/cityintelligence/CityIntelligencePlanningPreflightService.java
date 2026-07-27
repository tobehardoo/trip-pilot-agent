package io.github.tobehardoo.trippilot.cityintelligence;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;

import io.github.tobehardoo.trippilot.trip.TripService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class CityIntelligencePlanningPreflightService {

    private static final Set<String> REQUIRED_FACT_CATEGORIES = Set.of(
            "WEATHER",
            "ADDRESS",
            "COORDINATES",
            "OPENING_HOURS",
            "TICKET_PRICE",
            "RESERVATION_REQUIREMENT",
            "TEMPORARY_CLOSURE"
    );

    private final CityIntelligenceMapper mapper;
    private final CityIntelligencePrewarmService prewarmService;
    private final Duration waitTimeout;

    public CityIntelligencePlanningPreflightService(
            CityIntelligenceMapper mapper,
            CityIntelligencePrewarmService prewarmService,
            @Value("${app.city-intelligence.planning-wait-timeout:PT2S}")
            Duration waitTimeout
    ) {
        this.mapper = mapper;
        this.prewarmService = prewarmService;
        this.waitTimeout = waitTimeout;
    }

    public void prepare(TripService.TripResponse trip) {
        CityIntelligenceRefreshRecord refresh = mapper.findLatestRefresh(trip.id())
                .orElse(null);
        UUID refreshId;
        if (refresh == null) {
            refreshId = prewarmService.request(
                    trip.id(),
                    trip.destination(),
                    trip.startDate(),
                    trip.endDate()
            );
        } else if (needsRetry(trip, refresh)) {
            refreshId = prewarmService.request(
                    trip.id(),
                    trip.destination(),
                    trip.startDate(),
                    trip.endDate(),
                    retryKey(trip.id(), refresh)
            );
        } else if (isTerminal(refresh.status())) {
            return;
        } else {
            refreshId = refresh.id();
        }
        awaitTerminal(refreshId);
    }

    private boolean needsRetry(
            TripService.TripResponse trip,
            CityIntelligenceRefreshRecord refresh
    ) {
        return "FAILED".equals(refresh.status())
                || isSuccessful(refresh.status())
                && !hasAllRequiredFactCategories(trip);
    }

    private boolean hasAllRequiredFactCategories(TripService.TripResponse trip) {
        Set<String> freshCategories = new HashSet<>(
                mapper.findFreshApplicableFactCategories(
                        trip.id(),
                        Instant.now(),
                        trip.startDate(),
                        trip.endDate()
                )
        );
        return freshCategories.containsAll(REQUIRED_FACT_CATEGORIES);
    }

    private void awaitTerminal(UUID refreshId) {
        if (waitTimeout.isZero() || waitTimeout.isNegative()) {
            return;
        }
        Instant deadline = Instant.now().plus(waitTimeout);
        while (Instant.now().isBefore(deadline)) {
            CityIntelligenceRefreshRecord current = mapper.findRefresh(refreshId)
                    .orElse(null);
            if (current == null || isTerminal(current.status())) {
                return;
            }
            try {
                Thread.sleep(Math.min(50, waitTimeout.toMillis()));
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    private boolean isTerminal(String status) {
        return isSuccessful(status) || "FAILED".equals(status);
    }

    private boolean isSuccessful(String status) {
        return "SUCCEEDED".equals(status) || "PARTIAL".equals(status);
    }

    private UUID retryKey(UUID tripId, CityIntelligenceRefreshRecord refresh) {
        return UUID.nameUUIDFromBytes(
                ("city-planning-refresh-v1:"
                        + tripId + ":" + refresh.id() + ":" + refresh.version())
                        .getBytes(StandardCharsets.UTF_8)
        );
    }
}
