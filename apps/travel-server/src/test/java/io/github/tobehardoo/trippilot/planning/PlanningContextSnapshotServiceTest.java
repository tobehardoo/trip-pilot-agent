package io.github.tobehardoo.trippilot.planning;

import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.cityintelligence.CityIntelligenceMapper;
import io.github.tobehardoo.trippilot.guide.GuideImportMapper;
import io.github.tobehardoo.trippilot.guide.GuideImportService;
import io.github.tobehardoo.trippilot.trip.TripService;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PlanningContextSnapshotServiceTest {

    @Test
    void excludesLegacyFactsOutsideTheTripDateRange() {
        ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
        PlanningContextSnapshotMapper snapshotMapper = proxy(
                PlanningContextSnapshotMapper.class,
                (method, arguments) -> method.getName().equals("insert") ? 1 : null
        );
        GuideImportMapper guideMapper = proxy(
                GuideImportMapper.class,
                (method, arguments) -> switch (method.getName()) {
                    case "findActivePlanningTrustedFacts", "findPlanningMergeDecisions" -> List.of();
                    default -> defaultValue(method.getReturnType());
                }
        );
        CityIntelligenceMapper cityMapper = proxy(
                CityIntelligenceMapper.class,
                (method, arguments) -> method.getName().equals("findLatestRefresh")
                        ? Optional.empty()
                        : defaultValue(method.getReturnType())
        );
        PlanningContextSnapshotService service = new PlanningContextSnapshotService(
                snapshotMapper,
                guideMapper,
                cityMapper,
                new PlanningFactConflictResolver(objectMapper),
                objectMapper
        );
        UUID factId = UUID.randomUUID();
        GuideImportService.PlanningGuideFact legacyFact = new GuideImportService.PlanningGuideFact(
                UUID.randomUUID(), factId, "LOCATION", "old location", "old evidence",
                "PASTED_TEXT", "https://example.com/guide", "example.com", "Guide",
                0.8, LocalDate.of(2026, 7, 31),
                Instant.parse("2026-07-20T00:00:00Z"),
                Instant.parse("2026-08-10T00:00:00Z")
        );
        TripService.TripResponse trip = new TripService.TripResponse(
                UUID.randomUUID(), "Trip", "Guangzhou",
                LocalDate.of(2026, 8, 1), LocalDate.of(2026, 8, 2),
                "DRAFT", 0, null, Instant.now(), Instant.now()
        );

        PlanningContextSnapshotService.PlanningContextSnapshot snapshot = service.freeze(
                UUID.randomUUID(), UUID.randomUUID(), trip, List.of(legacyFact),
                Instant.parse("2026-07-25T00:00:00Z")
        );

        assertThat(snapshot.facts()).isEmpty();
        assertThat(snapshot.excludedFacts()).singleElement()
                .satisfies(excluded -> {
                    assertThat(excluded.factId()).isEqualTo(factId.toString());
                    assertThat(excluded.reason()).isEqualTo("EFFECTIVE_DATE_OUTSIDE_TRIP");
                });
    }

    @SuppressWarnings("unchecked")
    private <T> T proxy(Class<T> type, ProxyCall call) {
        return (T) Proxy.newProxyInstance(
                type.getClassLoader(),
                new Class<?>[]{type},
                (proxy, method, arguments) -> call.invoke(
                        method, arguments == null ? new Object[0] : arguments
                )
        );
    }

    private static Object defaultValue(Class<?> type) {
        if (type == int.class) {
            return 0;
        }
        if (type == boolean.class) {
            return false;
        }
        if (type == Optional.class) {
            return Optional.empty();
        }
        if (type == List.class) {
            return List.of();
        }
        return null;
    }

    @FunctionalInterface
    private interface ProxyCall {
        Object invoke(Method method, Object[] arguments);
    }
}
