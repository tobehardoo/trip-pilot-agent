package io.github.tobehardoo.trippilot.cityintelligence;

import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.guide.GuideImportRequest;
import io.github.tobehardoo.trippilot.guide.GuideImportService;
import io.github.tobehardoo.trippilot.trip.TripMapper;
import io.github.tobehardoo.trippilot.trip.TripRecord;
import org.springframework.stereotype.Service;

@Service
public class CityIntelligenceRefreshProcessor {

    private static final int MAX_PROVIDER_ATTEMPTS = 2;
    private static final int MAX_ERROR_MESSAGE_LENGTH = 500;

    private final CityIntelligenceMapper mapper;
    private final TripMapper tripMapper;
    private final CitySourceMapper sourceMapper;
    private final GuideImportService guideImportService;
    private final ObjectMapper objectMapper;

    public CityIntelligenceRefreshProcessor(
            CityIntelligenceMapper mapper,
            TripMapper tripMapper,
            CitySourceMapper sourceMapper,
            GuideImportService guideImportService,
            ObjectMapper objectMapper
    ) {
        this.mapper = mapper;
        this.tripMapper = tripMapper;
        this.sourceMapper = sourceMapper;
        this.guideImportService = guideImportService;
        this.objectMapper = objectMapper;
    }

    public void process(UUID refreshId) {
        CityIntelligenceRefreshRecord refresh = mapper.findRefresh(refreshId).orElse(null);
        if (refresh == null || isSuccessful(refresh.status())) {
            return;
        }
        Instant startedAt = Instant.now();
        if (mapper.markRunning(refreshId, refresh.version(), startedAt) != 1) {
            return;
        }

        TripRecord trip = tripMapper.findById(refresh.tripId()).orElse(null);
        if (trip == null) {
            completeFailure(
                    refreshId,
                    0,
                    "CITY_INTELLIGENCE_TRIP_NOT_FOUND",
                    "Trip was not found"
            );
            return;
        }

        List<ProviderResult> providers = new ArrayList<>();
        ProviderResult cityProvider = runProvider(
                "guide-agent",
                "高德城市情报",
                "CITY_INTELLIGENCE",
                () -> guideImportService.create(
                        trip.ownerId(),
                        trip.id(),
                        new GuideImportRequest(
                                null,
                                "CITY_INTELLIGENCE",
                                null,
                                null,
                                trip.destination(),
                                trip.startDate(),
                                trip.endDate()
                        )
                )
        );
        providers.add(cityProvider);
        for (CitySourceRecord source
                : sourceMapper.findAll(refresh.cityCode(), true, "APPROVED")) {
            providers.add(runProvider(
                    "registered-source",
                    source.sourceName(),
                    source.sourceType(),
                    () -> guideImportService.createRegisteredSource(
                            trip.ownerId(),
                            trip.id(),
                            source
                    )
            ));
        }

        long successes = providers.stream().filter(ProviderResult::succeeded).count();
        String status = successes == providers.size()
                ? "SUCCEEDED"
                : successes == 0 ? "FAILED" : "PARTIAL";
        String errorCode = switch (status) {
            case "FAILED" -> "CITY_INTELLIGENCE_PROVIDER_FAILED";
            case "PARTIAL" -> "CITY_INTELLIGENCE_PARTIAL";
            default -> null;
        };
        String errorMessage = switch (status) {
            case "FAILED" -> cityProvider.errorMessage();
            case "PARTIAL" -> "One or more city intelligence sources failed";
            default -> null;
        };
        mapper.completeRefresh(
                refreshId,
                status,
                diagnosticsJson(cityProvider.attempts(), status, errorCode, providers),
                Instant.now(),
                errorCode,
                errorMessage
        );
    }

    private void completeFailure(
            UUID refreshId,
            int attempts,
            String errorCode,
            String errorMessage
    ) {
        mapper.completeRefresh(
                refreshId,
                "FAILED",
                diagnosticsJson(attempts, "FAILED", errorCode, List.of()),
                Instant.now(),
                errorCode,
                errorMessage
        );
    }

    private ProviderResult runProvider(
            String provider,
            String sourceName,
            String sourceType,
            Runnable action
    ) {
        RuntimeException lastFailure = null;
        for (int attempt = 1; attempt <= MAX_PROVIDER_ATTEMPTS; attempt++) {
            try {
                action.run();
                return new ProviderResult(
                        provider,
                        sourceName,
                        sourceType,
                        attempt,
                        "SUCCEEDED",
                        null,
                        null
                );
            } catch (RuntimeException exception) {
                lastFailure = exception;
            }
        }
        return new ProviderResult(
                provider,
                sourceName,
                sourceType,
                MAX_PROVIDER_ATTEMPTS,
                "FAILED",
                "PROVIDER_FAILED",
                safeMessage(lastFailure)
        );
    }

    private String diagnosticsJson(
            int attempts,
            String outcome,
            String errorCode,
            List<ProviderResult> providers
    ) {
        Map<String, Object> diagnostics = new LinkedHashMap<>();
        diagnostics.put("provider", "guide-agent");
        diagnostics.put("attempts", attempts);
        diagnostics.put("outcome", outcome);
        diagnostics.put("providers", providers);
        if (errorCode != null) {
            diagnostics.put("errorCode", errorCode);
        }
        try {
            return objectMapper.writeValueAsString(diagnostics);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException(
                    "Could not serialize city intelligence diagnostics",
                    exception
            );
        }
    }

    private String safeMessage(RuntimeException failure) {
        String message = failure == null ? null : failure.getMessage();
        if (message == null || message.isBlank()) {
            message = failure == null
                    ? "City intelligence provider failed"
                    : failure.getClass().getSimpleName();
        }
        return message.substring(0, Math.min(message.length(), MAX_ERROR_MESSAGE_LENGTH));
    }

    private boolean isSuccessful(String status) {
        return "SUCCEEDED".equals(status) || "PARTIAL".equals(status);
    }

    private record ProviderResult(
            String provider,
            String sourceName,
            String sourceType,
            int attempts,
            String outcome,
            String errorCode,
            String errorMessage
    ) {
        private boolean succeeded() {
            return "SUCCEEDED".equals(outcome);
        }
    }
}
