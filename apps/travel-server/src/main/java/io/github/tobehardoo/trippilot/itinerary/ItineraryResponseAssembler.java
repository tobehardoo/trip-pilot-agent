package io.github.tobehardoo.trippilot.itinerary;

import java.math.BigDecimal;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent;
import io.github.tobehardoo.trippilot.planning.PlanningFactImpactMapper;
import org.springframework.stereotype.Component;

/**
 * Builds the immutable response view of an itinerary version from the
 * persisted mapper records.  Split out of {@link ItineraryService} so the
 * service keeps only orchestration and the version factory.
 */
@Component
public class ItineraryResponseAssembler {

    private final ItineraryMapper itineraryMapper;
    private final ObjectMapper objectMapper;
    private final PlanningFactImpactMapper factImpactMapper;
    private final ItineraryPlanningDecisionMapper planningDecisionMapper;

    public ItineraryResponseAssembler(
            ItineraryMapper itineraryMapper,
            ObjectMapper objectMapper,
            PlanningFactImpactMapper factImpactMapper,
            ItineraryPlanningDecisionMapper planningDecisionMapper
    ) {
        this.itineraryMapper = itineraryMapper;
        this.objectMapper = objectMapper;
        this.factImpactMapper = factImpactMapper;
        this.planningDecisionMapper = planningDecisionMapper;
    }

    public ItineraryService.ItineraryResponse toItineraryResponse(ItineraryMapper.CurrentVersion version) {
        List<ItineraryService.DayResponse> days = itineraryMapper.findDays(version.id()).stream()
                .map(day -> new ItineraryService.DayResponse(
                        day.date(),
                        itineraryMapper.findActivities(day.id()).stream()
                                .map(this::toActivityResponse)
                                .toList(),
                        itineraryMapper.findTransitLegs(day.id()).stream()
                                .map(this::toTransitLegResponse)
                                .toList(),
                        day.dayType()
                ))
                .toList();
        return new ItineraryService.ItineraryResponse(
                version.id(), version.versionNumber(), version.parentVersionId(), version.title(),
                humanVisibleTotalCost(version.estimatedTotalCost(), days),
                responseProvider(version.provider(), days), days,
                toKnowledgeResponse(version.id()),
                factImpactMapper.findByVersion(version.id()).stream()
                        .map(impact -> new ItineraryService.FactImpactResponse(
                                impact.factId(), impact.category(),
                                impact.applicableDate(), impact.effect(),
                                impact.targetPoiId(), impact.targetName(), impact.reason(),
                                impact.sourceName(), impact.sourceType(),
                                impact.sourceUrl(), impact.reliabilityLevel(),
                                impact.checkedAt(), impact.evidence(), impact.stale(),
                                impact.conflicted(), impact.refreshFailed()
                        ))
                        .toList(),
                version.accommodationStatus(), version.accommodationLabel(),
                readPlanningDecisions(version.id()),
                version.createdAt(), version.rollbackFromVersionId()
        );
    }

    /**
     * Reads the version's persisted planning-decision explanations (③ 决策解释上屏).
     * A version produced by planning carries them; user-edit / rollback versions
     * have no decision row and return an empty list (never fabricated).
     */
    private List<PlanningCompletedEvent.DecisionExplanation> readPlanningDecisions(UUID versionId) {
        java.util.Optional<String> stored = planningDecisionMapper.findDecisionsJson(versionId);
        if (stored.isEmpty()) {
            return List.of();
        }
        try {
            return objectMapper.readValue(
                    stored.get(),
                    new TypeReference<java.util.List<PlanningCompletedEvent.DecisionExplanation>>() { });
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored itinerary planning decisions are invalid", exception);
        }
    }

    private String responseProvider(String storedProvider, List<ItineraryService.DayResponse> days) {
        Set<String> providers = new HashSet<>();
        providers.add(storedProvider);
        days.forEach(day -> {
            day.activities().forEach(activity -> providers.add(activity.source()));
            day.transitLegs().forEach(leg -> providers.add(leg.provider()));
        });
        return providers.contains("AMAP") && providers.contains("DEMO")
                ? "MIXED" : storedProvider;
    }

    private static BigDecimal humanVisibleTotalCost(
            BigDecimal storedTotal,
            List<ItineraryService.DayResponse> days
    ) {
        BigDecimal roadTolls = days.stream()
                .flatMap(day -> day.transitLegs().stream())
                .filter(leg -> "DRIVING".equals(leg.mode()))
                .map(ItineraryService.TransitLegResponse::estimatedCost)
                .filter(java.util.Objects::nonNull)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        return storedTotal.subtract(roadTolls).max(BigDecimal.ZERO);
    }

    public ItineraryService.KnowledgeResponse toKnowledgeResponse(UUID versionId) {
        return itineraryMapper.findKnowledge(versionId)
                .map(knowledge -> new ItineraryService.KnowledgeResponse(
                        knowledge.status(), knowledge.query(),
                        itineraryMapper.findKnowledgeCitations(versionId).stream()
                                .map(citation -> new ItineraryService.KnowledgeCitationResponse(
                                        citation.documentId(), citation.documentVersion(),
                                        citation.chunkId(), citation.chunkIndex(), citation.title(),
                                        citation.sourceUrl(), citation.sourceName(), citation.collectedAt(),
                                        citation.reliabilityLevel(), citation.similarity()
                                ))
                                .toList(),
                        new ItineraryService.KnowledgeFreshnessResponse(
                                knowledge.freshnessStatus(), knowledge.freshnessCheckedAt(),
                                knowledge.staleReason()
                        ),
                        knowledge.message()
                ))
                .orElseGet(() -> new ItineraryService.KnowledgeResponse(
                        "UNAVAILABLE", "未记录", List.of(),
                        new ItineraryService.KnowledgeFreshnessResponse("UNAVAILABLE", null, null),
                        "该行程版本未包含知识引用"
                ));
    }

    private ItineraryService.ActivityResponse toActivityResponse(ItineraryMapper.StoredActivity activity) {
        return new ItineraryService.ActivityResponse(
                activity.id(), activity.title(), activity.startTime(), activity.endTime(),
                activity.estimatedCost(), activity.source(), activity.providerPoiId(),
                activity.longitude() == null
                        ? null
                        : new ItineraryService.CoordinatesResponse(activity.longitude(), activity.latitude()),
                activity.address(), activity.locked(),
                activity.typeCode(), activity.typeName(),
                activity.kind(), activity.timeFixed(),
                activity.costSource() == null ? "UNKNOWN" : activity.costSource()
        );
    }

    public ItineraryService.TransitLegResponse toTransitLegResponse(ItineraryMapper.StoredTransitLeg leg) {
        TransitLegSemantics.Presentation presentation = TransitLegSemantics.present(
                leg.mode(), leg.durationSeconds(), leg.provider(), leg.estimated(), leg.estimatedCost());
        return new ItineraryService.TransitLegResponse(
                leg.id(), leg.legOrder(), leg.fromActivityId(), leg.toActivityId(), leg.mode(),
                leg.distanceMeters(), leg.durationSeconds(), leg.provider(), leg.estimated(),
                readPolyline(leg.polylineJson()), leg.locked(), leg.estimatedCost(),
                leg.providerRouteId(), leg.calculatedAt(), leg.stale(),
                presentation.modeLabel(), presentation.routeDurationSeconds(),
                presentation.waitSeconds(), presentation.costSource(),
                presentation.costMeaning(), presentation.displayCost()
        );
    }

    private List<ItineraryService.CoordinatesResponse> readPolyline(String polylineJson) {
        try {
            return objectMapper.readValue(polylineJson, new TypeReference<>() {
            });
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored transit leg polyline is invalid", exception);
        }
    }
}
