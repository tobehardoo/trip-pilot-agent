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
                version.estimatedTotalCost(), version.provider(), days,
                toKnowledgeResponse(version.id()), version.createdAt()
        );
    }

    private KnowledgeResponse toKnowledgeResponse(UUID versionId) {
        return itineraryMapper.findKnowledge(versionId)
                .map(knowledge -> new KnowledgeResponse(
                        knowledge.status(), knowledge.query(),
                        itineraryMapper.findKnowledgeCitations(versionId).stream()
                                .map(citation -> new KnowledgeCitationResponse(
                                        citation.documentId(), citation.documentVersion(),
                                        citation.chunkId(), citation.chunkIndex(), citation.title(),
                                        citation.sourceUrl(), citation.sourceName(), citation.collectedAt(),
                                        citation.reliabilityLevel(), citation.similarity()
                                ))
                                .toList(),
                        new KnowledgeFreshnessResponse(
                                knowledge.freshnessStatus(), knowledge.freshnessCheckedAt(),
                                knowledge.staleReason()
                        ),
                        knowledge.message()
                ))
                .orElseGet(() -> new KnowledgeResponse(
                        "UNAVAILABLE", "未记录", List.of(),
                        new KnowledgeFreshnessResponse("UNAVAILABLE", null, null),
                        "该行程版本未包含知识引用"
                ));
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
            KnowledgeResponse knowledge,
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

    public record KnowledgeResponse(
            String status,
            String query,
            List<KnowledgeCitationResponse> citations,
            KnowledgeFreshnessResponse freshness,
            String message
    ) {
    }

    public record KnowledgeCitationResponse(
            String documentId,
            int documentVersion,
            String chunkId,
            int chunkIndex,
            String title,
            String sourceUrl,
            String sourceName,
            OffsetDateTime collectedAt,
            String reliabilityLevel,
            double similarity
    ) {
    }

    public record KnowledgeFreshnessResponse(
            String status,
            OffsetDateTime checkedAt,
            String staleReason
    ) {
    }
}
