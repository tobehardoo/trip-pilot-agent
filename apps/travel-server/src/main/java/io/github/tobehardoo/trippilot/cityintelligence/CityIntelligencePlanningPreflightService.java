package io.github.tobehardoo.trippilot.cityintelligence;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.UUID;

import io.github.tobehardoo.trippilot.trip.TripService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class CityIntelligencePlanningPreflightService {

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
        if (refresh == null || isTerminal(refresh.status())) {
            refreshId = prewarmService.request(
                    trip.id(),
                    trip.destination(),
                    trip.startDate(),
                    trip.endDate(),
                    refreshKey(trip.id(), refresh)
            );
        } else {
            refreshId = refresh.id();
        }
        awaitTerminal(refreshId);
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

    private UUID refreshKey(UUID tripId, CityIntelligenceRefreshRecord refresh) {
        if (refresh == null) {
            return UUID.nameUUIDFromBytes(
                    ("city-planning-refresh-v2:" + tripId + ":initial")
                            .getBytes(StandardCharsets.UTF_8)
            );
        }
        return UUID.nameUUIDFromBytes(
                ("city-planning-refresh-v2:"
                        + tripId + ":" + refresh.id() + ":" + refresh.version())
                        .getBytes(StandardCharsets.UTF_8)
        );
    }

}
