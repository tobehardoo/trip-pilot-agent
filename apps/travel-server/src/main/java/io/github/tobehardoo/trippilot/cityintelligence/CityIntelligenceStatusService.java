package io.github.tobehardoo.trippilot.cityintelligence;

import java.time.Instant;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.trip.TripService;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CityIntelligenceStatusService {

    private final CityIntelligenceMapper mapper;
    private final TripService tripService;
    private final CityIntelligencePrewarmService prewarmService;
    private final ObjectMapper objectMapper;

    public CityIntelligenceStatusService(
            CityIntelligenceMapper mapper,
            TripService tripService,
            CityIntelligencePrewarmService prewarmService,
            ObjectMapper objectMapper
    ) {
        this.mapper = mapper;
        this.tripService = tripService;
        this.prewarmService = prewarmService;
        this.objectMapper = objectMapper;
    }

    @Transactional(readOnly = true)
    public CityIntelligenceStatusResponse get(UUID ownerId, UUID tripId) {
        tripService.get(ownerId, tripId);
        CityIntelligenceRefreshRecord refresh = mapper.findLatestRefresh(tripId)
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND,
                        "CITY_INTELLIGENCE_NOT_FOUND",
                        "City intelligence has not been requested for this trip"
                ));
        boolean stale = !"SUCCEEDED".equals(refresh.status())
                && !"PARTIAL".equals(refresh.status());
        return new CityIntelligenceStatusResponse(
                tripId,
                refresh.id(),
                refresh.cityCode(),
                refresh.status(),
                stale,
                refresh.attemptCount(),
                readJson(refresh.requestedCategoriesJson()),
                readJson(refresh.providerDiagnosticsJson()),
                refresh.startedAt(),
                refresh.completedAt(),
                refresh.errorCode(),
                refresh.errorMessage(),
                refresh.updatedAt()
        );
    }

    @Transactional
    public CityIntelligenceStatusResponse refresh(
            UUID ownerId,
            UUID tripId,
            UUID idempotencyKey
    ) {
        TripService.TripResponse trip = tripService.get(ownerId, tripId);
        prewarmService.request(
                tripId,
                trip.destination(),
                trip.startDate(),
                trip.endDate(),
                idempotencyKey
        );
        return get(ownerId, tripId);
    }

    private JsonNode readJson(String value) {
        try {
            return objectMapper.readTree(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored city intelligence JSON is invalid", exception);
        }
    }

    public record CityIntelligenceStatusResponse(
            UUID tripId,
            UUID refreshId,
            String cityCode,
            String status,
            boolean stale,
            int attemptCount,
            JsonNode requestedCategories,
            JsonNode providerDiagnostics,
            Instant startedAt,
            Instant completedAt,
            String errorCode,
            String errorMessage,
            Instant updatedAt
    ) {
    }
}
