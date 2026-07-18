package io.github.tobehardoo.trippilot.itinerary;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ItineraryService {

    private final ItineraryMapper itineraryMapper;
    private final ObjectMapper objectMapper;

    public ItineraryService(ItineraryMapper itineraryMapper, ObjectMapper objectMapper) {
        this.itineraryMapper = itineraryMapper;
        this.objectMapper = objectMapper;
    }

    @Transactional(readOnly = true)
    public ItineraryResponse getCurrent(UUID ownerId, UUID tripId) {
        ItineraryMapper.CurrentVersion version = itineraryMapper.findCurrentVersionOwned(tripId, ownerId)
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND, "ITINERARY_NOT_FOUND", "Itinerary was not found"
                ));
        List<DayResponse> days = itineraryMapper.findDays(version.id()).stream()
                .map(day -> new DayResponse(
                        day.date(),
                        itineraryMapper.findActivities(day.id()).stream()
                                .map(this::toActivityResponse)
                                .toList(),
                        itineraryMapper.findTransitLegs(day.id()).stream()
                                .map(this::toTransitLegResponse)
                                .toList()
                ))
                .toList();
        return new ItineraryResponse(
                version.id(), version.versionNumber(), version.parentVersionId(), version.title(),
                version.estimatedTotalCost(), version.provider(), days, version.createdAt()
        );
    }

    private ActivityResponse toActivityResponse(ItineraryMapper.StoredActivity activity) {
        return new ActivityResponse(
                activity.id(), activity.title(), activity.startTime(), activity.endTime(),
                activity.estimatedCost(), activity.source(), activity.providerPoiId(),
                activity.longitude() == null
                        ? null
                        : new CoordinatesResponse(activity.longitude(), activity.latitude()),
                activity.address()
        );
    }

    private TransitLegResponse toTransitLegResponse(ItineraryMapper.StoredTransitLeg leg) {
        return new TransitLegResponse(
                leg.id(), leg.legOrder(), leg.fromActivityId(), leg.toActivityId(), leg.mode(),
                leg.distanceMeters(), leg.durationSeconds(), leg.provider(), leg.estimated(),
                readPolyline(leg.polylineJson())
        );
    }

    private List<CoordinatesResponse> readPolyline(String polylineJson) {
        try {
            return objectMapper.readValue(polylineJson, new TypeReference<>() {
            });
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored transit leg polyline is invalid", exception);
        }
    }

    public record ItineraryResponse(
            UUID versionId,
            int versionNumber,
            UUID parentVersionId,
            String title,
            BigDecimal estimatedTotalCost,
            String provider,
            List<DayResponse> days,
            Instant createdAt
    ) {
    }

    public record DayResponse(
            LocalDate date,
            List<ActivityResponse> activities,
            List<TransitLegResponse> transitLegs
    ) {
    }

    public record ActivityResponse(
            UUID id,
            String title,
            OffsetDateTime startTime,
            OffsetDateTime endTime,
            BigDecimal estimatedCost,
            String source,
            String providerPoiId,
            CoordinatesResponse coordinates,
            String address
    ) {
    }

    public record CoordinatesResponse(BigDecimal longitude, BigDecimal latitude) {
    }

    public record TransitLegResponse(
            UUID id,
            int legOrder,
            UUID fromActivityId,
            UUID toActivityId,
            String mode,
            int distanceMeters,
            int durationSeconds,
            String provider,
            boolean estimated,
            List<CoordinatesResponse> polyline
    ) {
    }
}
