package io.github.tobehardoo.trippilot.cityintelligence;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.infrastructure.mq.OutboxEventRecord;
import io.github.tobehardoo.trippilot.infrastructure.mq.OutboxMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CityIntelligencePrewarmService {

    static final List<String> REQUIRED_CATEGORIES = List.of(
            "CURRENT_WEATHER",
            "DAILY_FORECAST",
            "ATTRACTION_DETAILS",
            "OPENING_HOURS",
            "TICKET_PRICE",
            "RESERVATION_REQUIREMENT",
            "TEMPORARY_CLOSURE"
    );

    private final CityIntelligenceMapper mapper;
    private final OutboxMapper outboxMapper;
    private final ObjectMapper objectMapper;

    public CityIntelligencePrewarmService(
            CityIntelligenceMapper mapper,
            OutboxMapper outboxMapper,
            ObjectMapper objectMapper
    ) {
        this.mapper = mapper;
        this.outboxMapper = outboxMapper;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public UUID request(
            UUID tripId,
            String city,
            LocalDate startDate,
            LocalDate endDate
    ) {
        UUID idempotencyKey = UUID.nameUUIDFromBytes(
                ("city-prewarm-v1:" + tripId + ":" + startDate + ":" + endDate)
                        .getBytes(StandardCharsets.UTF_8)
        );
        return request(tripId, city, startDate, endDate, idempotencyKey);
    }

    @Transactional
    public UUID request(
            UUID tripId,
            String city,
            LocalDate startDate,
            LocalDate endDate,
            UUID idempotencyKey
    ) {
        return request(tripId, city, cityCode(city), startDate, endDate, idempotencyKey);
    }

    @Transactional
    public UUID request(UUID tripId, String city, String explicitCityCode, LocalDate startDate, LocalDate endDate) {
        UUID idempotencyKey = UUID.nameUUIDFromBytes(("city-prewarm-v1:" + tripId + ":" + startDate + ":" + endDate)
                .getBytes(StandardCharsets.UTF_8));
        return request(tripId, city, explicitCityCode, startDate, endDate, idempotencyKey);
    }

    @Transactional
    public UUID request(UUID tripId, String city, String explicitCityCode, LocalDate startDate, LocalDate endDate, UUID idempotencyKey) {
        String cityCode = explicitCityCode;
        UUID refreshId = UUID.randomUUID();
        CityIntelligenceRefreshRecord refresh = new CityIntelligenceRefreshRecord(
                refreshId,
                tripId,
                cityCode,
                idempotencyKey,
                "QUEUED",
                writeJson(REQUIRED_CATEGORIES),
                "[]",
                0,
                null,
                null,
                null,
                null,
                0,
                null,
                null
        );
        if (mapper.insertRefresh(refresh) == 0) {
            return mapper.findByIdempotencyKey(tripId, idempotencyKey)
                    .or(() -> mapper.findLatestRefresh(tripId))
                    .map(CityIntelligenceRefreshRecord::id)
                    .orElseThrow(() -> new IllegalStateException(
                            "City intelligence refresh conflict could not be resolved"
                    ));
        }
        List<String> sourceIds = mapper.findApprovedSourceIds(cityCode);
        if (sourceIds.isEmpty()) {
            // RegionRef uses the stable six-digit adcode; older registry rows use legacy aliases.
            sourceIds = mapper.findApprovedSourceIds(cityCode(city));
        }
        Instant now = Instant.now();
        UUID eventId = UUID.randomUUID();
        CityRefreshCommand command = new CityRefreshCommand(
                "CITY_INTELLIGENCE_REFRESH_REQUESTED",
                1,
                eventId,
                refreshId,
                tripId,
                now,
                new CityRefreshPayload(
                        city,
                        cityCode,
                        startDate,
                        endDate,
                        sourceIds,
                        REQUIRED_CATEGORIES,
                        idempotencyKey
                )
        );
        outboxMapper.insert(new OutboxEventRecord(
                eventId,
                "CITY_INTELLIGENCE_REFRESH",
                tripId,
                "CITY_INTELLIGENCE_REFRESH_REQUESTED",
                "city-intelligence.refresh",
                writeJson(command),
                "PENDING",
                0,
                now,
                null,
                now,
                null
        ));
        return refreshId;
    }

    public static String cityCode(String city) {
        String normalized = city.trim().replaceFirst("市$", "");
        return Map.of(
                "广州", "CN-GD-GZ",
                "北京", "CN-BJ",
                "上海", "CN-SH"
        ).getOrDefault(normalized, "UNREGISTERED");
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not serialize city refresh command", exception);
        }
    }

    private record CityRefreshCommand(
            String eventType,
            int schemaVersion,
            UUID eventId,
            UUID refreshId,
            UUID tripId,
            Instant occurredAt,
            CityRefreshPayload payload
    ) {
    }

    private record CityRefreshPayload(
            String city,
            String cityCode,
            LocalDate startDate,
            LocalDate endDate,
            List<String> sourceIds,
            List<String> requiredCategories,
            UUID idempotencyKey
    ) {
    }
}
