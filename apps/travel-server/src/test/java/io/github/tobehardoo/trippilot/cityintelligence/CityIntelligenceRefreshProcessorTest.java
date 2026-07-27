package io.github.tobehardoo.trippilot.cityintelligence;

import java.lang.reflect.Proxy;
import java.lang.reflect.Method;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.Queue;
import java.util.UUID;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.guide.GuideImportRequest;
import io.github.tobehardoo.trippilot.guide.GuideImportService;
import io.github.tobehardoo.trippilot.trip.TripMapper;
import io.github.tobehardoo.trippilot.trip.TripRecord;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class CityIntelligenceRefreshProcessorTest {

    @Test
    void processesAtMostOnceWhenDuplicateDeliveriesRace() {
        Fixture fixture = fixture(1, 0);

        fixture.processor.process(fixture.refreshId);
        fixture.processor.process(fixture.refreshId);

        assertThat(fixture.guideImporter.attempts).isEqualTo(1);
        assertThat(fixture.completions).singleElement().satisfies(completion -> {
            assertThat(completion.status()).isEqualTo("SUCCEEDED");
            assertThat(completion.errorCode()).isNull();
            assertThat(completion.errorMessage()).isNull();
        });
    }

    @Test
    void boundsProviderAttemptsAndPersistsFailureDiagnostics() {
        Fixture fixture = fixture(1);
        fixture.guideImporter.failure = new RuntimeException("provider unavailable");

        fixture.processor.process(fixture.refreshId);

        assertThat(fixture.guideImporter.attempts).isEqualTo(2);
        assertThat(fixture.completions).singleElement().satisfies(completion -> {
            assertThat(completion.status()).isEqualTo("FAILED");
            assertThat(completion.errorCode())
                    .isEqualTo("CITY_INTELLIGENCE_PROVIDER_FAILED");
            assertThat(completion.errorMessage()).isEqualTo("provider unavailable");
            assertThat(completion.diagnosticsJson()).contains("\"attempts\":2");
        });
    }

    @Test
    void importsApprovedOfficialSourcesAndReportsPartialFailure() {
        CitySourceRecord museum = source("广州博物馆", "OFFICIAL_ATTRACTION");
        Fixture fixture = fixture(List.of(museum), 1);
        fixture.guideImporter.officialFailure = new RuntimeException("official unavailable");

        fixture.processor.process(fixture.refreshId);

        assertThat(fixture.guideImporter.attempts).isEqualTo(1);
        assertThat(fixture.guideImporter.officialAttempts).isEqualTo(2);
        assertThat(fixture.completions).singleElement().satisfies(completion -> {
            assertThat(completion.status()).isEqualTo("PARTIAL");
            assertThat(completion.errorCode()).isEqualTo("CITY_INTELLIGENCE_PARTIAL");
            assertThat(completion.diagnosticsJson())
                    .contains("\"sourceName\":\"广州博物馆\"")
                    .contains("\"outcome\":\"FAILED\"");
        });
    }

    private Fixture fixture(Integer... markRunningResults) {
        return fixture(List.of(), markRunningResults);
    }

    private Fixture fixture(
            List<CitySourceRecord> sources,
            Integer... markRunningResults
    ) {
        UUID ownerId = UUID.randomUUID();
        UUID tripId = UUID.randomUUID();
        UUID refreshId = UUID.randomUUID();
        CityIntelligenceRefreshRecord refresh = new CityIntelligenceRefreshRecord(
                refreshId,
                tripId,
                "CN-GD-GZ",
                UUID.randomUUID(),
                "QUEUED",
                "[]",
                "[]",
                0,
                null,
                null,
                null,
                null,
                0,
                Instant.now(),
                Instant.now()
        );
        TripRecord trip = new TripRecord(
                tripId,
                ownerId,
                "广州旅行",
                "广州",
                LocalDate.of(2026, 8, 1),
                LocalDate.of(2026, 8, 4),
                "DRAFT",
                0,
                Instant.now(),
                Instant.now(),
                null
        );
        Queue<Integer> runningResults = new ArrayDeque<>(List.of(markRunningResults));
        List<Completion> completions = new ArrayList<>();
        CityIntelligenceMapper mapper = proxy(
                CityIntelligenceMapper.class,
                (method, arguments) -> switch (method.getName()) {
                    case "findRefresh" -> Optional.of(refresh);
                    case "markRunning" -> runningResults.remove();
                    case "completeRefresh" -> {
                        completions.add(new Completion(
                                (String) arguments[1],
                                (String) arguments[2],
                                (String) arguments[4],
                                (String) arguments[5]
                        ));
                        yield 1;
                    }
                    default -> defaultValue(method.getReturnType());
                }
        );
        TripMapper tripMapper = proxy(
                TripMapper.class,
                (method, arguments) -> "findById".equals(method.getName())
                        ? Optional.of(trip)
                        : defaultValue(method.getReturnType())
        );
        CitySourceMapper sourceMapper = proxy(
                CitySourceMapper.class,
                (method, arguments) -> "findAll".equals(method.getName())
                        ? sources
                        : defaultValue(method.getReturnType())
        );
        RecordingGuideImporter guideImporter = new RecordingGuideImporter();
        return new Fixture(
                refreshId,
                guideImporter,
                completions,
                new CityIntelligenceRefreshProcessor(
                        mapper,
                        tripMapper,
                        sourceMapper,
                        guideImporter,
                        new ObjectMapper().findAndRegisterModules()
                )
        );
    }

    private CitySourceRecord source(String name, String sourceType) {
        Instant now = Instant.now();
        return new CitySourceRecord(
                UUID.randomUUID(),
                "CN-GD-GZ",
                "广州",
                name,
                "https://museum.example/visit",
                sourceType,
                "AUTHORITATIVE",
                true,
                "ATTRACTION_VISIT_PAGE",
                "{}",
                "APPROVED",
                "verified",
                UUID.randomUUID(),
                now,
                0,
                now,
                now
        );
    }

    @SuppressWarnings("unchecked")
    private <T> T proxy(Class<T> type, ProxyCall call) {
        return (T) Proxy.newProxyInstance(
                type.getClassLoader(),
                new Class<?>[]{type},
                (proxy, method, arguments) -> call.invoke(
                        method,
                        arguments == null ? new Object[0] : arguments
                )
        );
    }

    private Object defaultValue(Class<?> type) {
        if (type == int.class) {
            return 0;
        }
        if (type == boolean.class) {
            return false;
        }
        if (type == List.class) {
            return List.of();
        }
        if (type == Optional.class) {
            return Optional.empty();
        }
        return null;
    }

    @FunctionalInterface
    private interface ProxyCall {
        Object invoke(Method method, Object[] arguments);
    }

    private static final class RecordingGuideImporter extends GuideImportService {
        private int attempts;
        private int officialAttempts;
        private RuntimeException failure;
        private RuntimeException officialFailure;

        private RecordingGuideImporter() {
            super(null, null, null, null, null);
        }

        @Override
        public GuideImportResponse create(
                UUID ownerId,
                UUID tripId,
                GuideImportRequest request
        ) {
            attempts++;
            if (failure != null) {
                throw failure;
            }
            return null;
        }

        @Override
        public GuideImportResponse createRegisteredSource(
                UUID ownerId,
                UUID tripId,
                CitySourceRecord source
        ) {
            officialAttempts++;
            if (officialFailure != null) {
                throw officialFailure;
            }
            return null;
        }
    }

    private record Completion(
            String status,
            String diagnosticsJson,
            String errorCode,
            String errorMessage
    ) {
    }

    private record Fixture(
            UUID refreshId,
            RecordingGuideImporter guideImporter,
            List<Completion> completions,
            CityIntelligenceRefreshProcessor processor
    ) {
    }
}
