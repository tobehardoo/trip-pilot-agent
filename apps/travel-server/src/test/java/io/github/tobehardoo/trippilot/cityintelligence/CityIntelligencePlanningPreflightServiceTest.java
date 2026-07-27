package io.github.tobehardoo.trippilot.cityintelligence;

import java.lang.reflect.Proxy;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

import io.github.tobehardoo.trippilot.trip.TripService;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class CityIntelligencePlanningPreflightServiceTest {

    @Test
    void waitsForAnInFlightRefreshToReachATerminalState() {
        UUID refreshId = UUID.randomUUID();
        AtomicInteger refreshReads = new AtomicInteger();
        CityIntelligenceRefreshRecord running = refresh(refreshId, "RUNNING");
        CityIntelligenceRefreshRecord succeeded = refresh(refreshId, "SUCCEEDED");
        CityIntelligenceMapper mapper = (CityIntelligenceMapper) Proxy.newProxyInstance(
                CityIntelligenceMapper.class.getClassLoader(),
                new Class<?>[]{CityIntelligenceMapper.class},
                (proxy, method, arguments) -> switch (method.getName()) {
                    case "findLatestRefresh" -> Optional.of(running);
                    case "findRefresh" -> Optional.of(
                            refreshReads.incrementAndGet() == 1 ? running : succeeded
                    );
                    default -> defaultValue(method.getReturnType());
                }
        );
        CityIntelligencePlanningPreflightService service =
                new CityIntelligencePlanningPreflightService(
                        mapper,
                        null,
                        Duration.ofMillis(200)
                );

        service.prepare(trip());

        assertThat(refreshReads).hasValue(2);
    }

    @Test
    void refreshesWhenOnlyOneRequiredFactCategoryIsFresh() {
        UUID refreshId = UUID.randomUUID();
        UUID requestedRefreshId = UUID.randomUUID();
        CityIntelligenceRefreshRecord succeeded = refresh(refreshId, "SUCCEEDED");
        CityIntelligenceMapper mapper = (CityIntelligenceMapper) Proxy.newProxyInstance(
                CityIntelligenceMapper.class.getClassLoader(),
                new Class<?>[]{CityIntelligenceMapper.class},
                (proxy, method, arguments) -> switch (method.getName()) {
                    case "findLatestRefresh" -> Optional.of(succeeded);
                    case "findFreshApplicableFactCategories" -> List.of("WEATHER");
                    default -> defaultValue(method.getReturnType());
                }
        );
        AtomicInteger requests = new AtomicInteger();
        CityIntelligencePrewarmService prewarmService =
                new CityIntelligencePrewarmService(null, null, null) {
                    @Override
                    public UUID request(
                            UUID tripId,
                            String city,
                            LocalDate startDate,
                            LocalDate endDate,
                            UUID idempotencyKey
                    ) {
                        requests.incrementAndGet();
                        return requestedRefreshId;
                    }
                };
        CityIntelligencePlanningPreflightService service =
                new CityIntelligencePlanningPreflightService(
                        mapper,
                        prewarmService,
                        Duration.ZERO
                );
        TripService.TripResponse trip = trip();

        service.prepare(trip);

        assertThat(requests).hasValue(1);
    }

    @Test
    void keepsACompletedRefreshWhenEveryRequiredCategoryIsFresh() {
        UUID refreshId = UUID.randomUUID();
        CityIntelligenceRefreshRecord succeeded = refresh(refreshId, "SUCCEEDED");
        CityIntelligenceMapper mapper = (CityIntelligenceMapper) Proxy.newProxyInstance(
                CityIntelligenceMapper.class.getClassLoader(),
                new Class<?>[]{CityIntelligenceMapper.class},
                (proxy, method, arguments) -> switch (method.getName()) {
                    case "findLatestRefresh" -> Optional.of(succeeded);
                    case "findFreshApplicableFactCategories" -> List.of(
                            "WEATHER",
                            "ADDRESS",
                            "COORDINATES",
                            "OPENING_HOURS",
                            "TICKET_PRICE",
                            "RESERVATION_REQUIREMENT",
                            "TEMPORARY_CLOSURE"
                    );
                    default -> defaultValue(method.getReturnType());
                }
        );
        AtomicInteger requests = new AtomicInteger();
        CityIntelligencePrewarmService prewarmService =
                new CityIntelligencePrewarmService(null, null, null) {
                    @Override
                    public UUID request(
                            UUID tripId,
                            String city,
                            LocalDate startDate,
                            LocalDate endDate,
                            UUID idempotencyKey
                    ) {
                        requests.incrementAndGet();
                        return UUID.randomUUID();
                    }
                };
        CityIntelligencePlanningPreflightService service =
                new CityIntelligencePlanningPreflightService(
                        mapper,
                        prewarmService,
                        Duration.ZERO
                );

        service.prepare(trip());

        assertThat(requests).hasValue(0);
    }

    private TripService.TripResponse trip() {
        return new TripService.TripResponse(
                UUID.randomUUID(),
                "北京行程",
                "北京",
                LocalDate.of(2026, 8, 1),
                LocalDate.of(2026, 8, 3),
                "DRAFT",
                0,
                null,
                Instant.now(),
                Instant.now(),
                null
        );
    }

    private CityIntelligenceRefreshRecord refresh(UUID id, String status) {
        return new CityIntelligenceRefreshRecord(
                id,
                UUID.randomUUID(),
                "CN-BJ",
                UUID.randomUUID(),
                status,
                "[]",
                "[]",
                1,
                Instant.now(),
                null,
                null,
                null,
                1,
                Instant.now(),
                Instant.now()
        );
    }

    private static Object defaultValue(Class<?> type) {
        if (type == boolean.class) {
            return false;
        }
        if (type == int.class) {
            return 0;
        }
        if (type == Optional.class) {
            return Optional.empty();
        }
        return null;
    }
}
