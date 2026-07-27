package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.TrustedFactRecord;
import org.springframework.stereotype.Component;

@Component
public class PlanningFactConflictResolver {

    private final ObjectMapper objectMapper;

    public PlanningFactConflictResolver(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public Resolution resolve(List<TrustedFactRecord> facts, Instant asOf) {
        Map<FactKey, List<RankedFact>> groups = new LinkedHashMap<>();
        for (TrustedFactRecord fact : facts) {
            JsonNode value = readValue(fact.normalizedValueJson());
            String poiName = value.path("poiName").asText("").trim();
            String entity = poiName.isEmpty()
                    ? fact.factId()
                    : poiName.toLowerCase(Locale.ROOT);
            groups.computeIfAbsent(
                    new FactKey(fact.category(), entity, fact.effectiveDate()),
                    ignored -> new ArrayList<>()
            ).add(new RankedFact(fact, value));
        }

        List<TrustedFactRecord> selectedFacts = new ArrayList<>();
        List<ResolvedConflict> conflicts = new ArrayList<>();
        for (List<RankedFact> group : groups.values()) {
            List<RankedFact> ranked = group.stream()
                    .sorted(comparator(asOf).reversed())
                    .toList();
            RankedFact selected = ranked.getFirst();
            selectedFacts.add(selected.fact());
            List<String> conflictIds = ranked.stream()
                    .skip(1)
                    .filter(candidate -> !candidate.value().equals(selected.value()))
                    .map(candidate -> candidate.fact().factId())
                    .toList();
            if (!conflictIds.isEmpty()) {
                List<String> downgraded = ranked.stream()
                        .skip(1)
                        .map(candidate -> candidate.fact().factId())
                        .toList();
                boolean needsManualReview = sameDecisionTier(
                        selected.fact(),
                        ranked.get(1).fact(),
                        asOf
                );
                conflicts.add(new ResolvedConflict(
                        selected.fact().factId(),
                        conflictIds,
                        downgraded,
                        decisionReason(selected.fact()),
                        needsManualReview
                ));
            }
        }
        return new Resolution(List.copyOf(selectedFacts), List.copyOf(conflicts));
    }

    private Comparator<RankedFact> comparator(Instant asOf) {
        return Comparator
                .comparingInt((RankedFact candidate) -> rankTier(candidate.fact()))
                .thenComparingInt(candidate ->
                        candidate.fact().expiresAt().isAfter(asOf) ? 1 : 0)
                .thenComparingDouble(candidate -> candidate.fact().confidence())
                .thenComparing(candidate -> candidate.fact().checkedAt())
                .thenComparing(candidate -> candidate.fact().factId());
    }

    private int rankTier(TrustedFactRecord fact) {
        int base = switch (fact.reliabilityLevel()) {
            case "OFFICIAL_ATTRACTION" -> 70;
            case "OFFICIAL_TOURISM" -> 60;
            case "WEATHER_PROVIDER" -> 50;
            case "MAP_PROVIDER" -> 40;
            case "PUBLIC_GUIDE" -> 30;
            case "COMMUNITY" -> 20;
            default -> 0;
        };
        return base + (fact.sourceReviewed() && base >= 60 ? 10 : 0);
    }

    private boolean sameDecisionTier(
            TrustedFactRecord first,
            TrustedFactRecord second,
            Instant asOf
    ) {
        return rankTier(first) == rankTier(second)
                && first.expiresAt().isAfter(asOf) == second.expiresAt().isAfter(asOf);
    }

    private String decisionReason(TrustedFactRecord selected) {
        if (selected.sourceReviewed() && rankTier(selected) >= 60) {
            return "selected reviewed official source across planning imports";
        }
        return "selected source across planning imports by reliability, freshness, and evidence";
    }

    private JsonNode readValue(String value) {
        try {
            return objectMapper.readTree(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored trusted fact JSON is invalid", exception);
        }
    }

    private record FactKey(String category, String entity, LocalDate effectiveDate) {
    }

    private record RankedFact(TrustedFactRecord fact, JsonNode value) {
    }

    public record Resolution(
            List<TrustedFactRecord> selectedFacts,
            List<ResolvedConflict> conflicts
    ) {
    }

    public record ResolvedConflict(
            String selectedFactId,
            List<String> conflictFactIds,
            List<String> downgradedFactIds,
            String reason,
            boolean needsManualReview
    ) {
    }
}
