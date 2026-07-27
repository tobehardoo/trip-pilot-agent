package io.github.tobehardoo.trippilot.planning;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.cityintelligence.CityIntelligenceMapper;
import io.github.tobehardoo.trippilot.cityintelligence.CityIntelligenceRefreshRecord;
import io.github.tobehardoo.trippilot.guide.GuideImportMapper;
import io.github.tobehardoo.trippilot.guide.GuideImportService;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.FactMergeDecisionRecord;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.TrustedFactRecord;
import io.github.tobehardoo.trippilot.trip.TripService;
import org.springframework.stereotype.Service;

@Service
public class PlanningContextSnapshotService {

    private static final int SCHEMA_VERSION = 3;

    private final PlanningContextSnapshotMapper snapshotMapper;
    private final GuideImportMapper guideImportMapper;
    private final CityIntelligenceMapper cityIntelligenceMapper;
    private final PlanningFactConflictResolver conflictResolver;
    private final ObjectMapper objectMapper;

    public PlanningContextSnapshotService(
            PlanningContextSnapshotMapper snapshotMapper,
            GuideImportMapper guideImportMapper,
            CityIntelligenceMapper cityIntelligenceMapper,
            PlanningFactConflictResolver conflictResolver,
            ObjectMapper objectMapper
    ) {
        this.snapshotMapper = snapshotMapper;
        this.guideImportMapper = guideImportMapper;
        this.cityIntelligenceMapper = cityIntelligenceMapper;
        this.conflictResolver = conflictResolver;
        this.objectMapper = objectMapper;
    }

    public PlanningContextSnapshot freeze(
            UUID ownerId,
            UUID taskId,
            TripService.TripResponse trip,
            List<GuideImportService.PlanningGuideFact> legacyFacts,
            Instant generatedAt
    ) {
        List<TrustedFactRecord> importedFacts = guideImportMapper
                .findActivePlanningTrustedFacts(trip.id(), ownerId);
        PlanningFactConflictResolver.Resolution resolution =
                conflictResolver.resolve(importedFacts, generatedAt);
        List<TrustedFactRecord> trusted = resolution.selectedFacts();
        Set<UUID> importsWithTrustedFacts = trusted.stream()
                .map(TrustedFactRecord::guideImportId)
                .collect(java.util.stream.Collectors.toSet());
        List<PlanningFact> facts = new ArrayList<>();
        List<ExcludedFact> excludedFacts = new ArrayList<>();

        for (TrustedFactRecord fact : trusted) {
            PlanningFact planningFact = toPlanningFact(fact, generatedAt);
            if (appliesToTrip(fact.effectiveDate(), trip.startDate(), trip.endDate())) {
                facts.add(planningFact);
            } else {
                excludedFacts.add(new ExcludedFact(
                        fact.factId(),
                        fact.category(),
                        fact.statement(),
                        "EFFECTIVE_DATE_OUTSIDE_TRIP"
                ));
            }
        }
        legacyFacts.stream()
                .filter(fact -> !importsWithTrustedFacts.contains(fact.guideImportId()))
                .forEach(fact -> {
                    PlanningFact planningFact = toPlanningFact(fact, generatedAt);
                    if (appliesToTrip(
                            fact.effectiveDate(), trip.startDate(), trip.endDate())) {
                        facts.add(planningFact);
                    } else {
                        excludedFacts.add(new ExcludedFact(
                                fact.factId().toString(),
                                fact.category(),
                                fact.statement(),
                                "EFFECTIVE_DATE_OUTSIDE_TRIP"
                        ));
                    }
                });

        List<Source> sources = uniqueSources(facts);
        List<Conflict> conflicts = new ArrayList<>(guideImportMapper
                .findPlanningMergeDecisions(trip.id(), ownerId).stream()
                .map(this::toConflict)
                .toList());
        resolution.conflicts().stream()
                .map(this::toConflict)
                .forEach(conflicts::add);
        CityIntelligenceRefreshRecord refresh = cityIntelligenceMapper
                .findLatestRefresh(trip.id())
                .orElse(null);
        boolean stale = facts.stream().anyMatch(PlanningFact::stale)
                || refresh == null
                || !Set.of("SUCCEEDED", "PARTIAL").contains(refresh.status());
        List<Diagnostic> diagnostics = refresh == null
                ? List.of(new Diagnostic(
                        "CITY_INTELLIGENCE_MISSING",
                        "No city intelligence refresh exists",
                        null
                ))
                : List.of(new Diagnostic(
                        refresh.errorCode(),
                        refresh.errorMessage(),
                        refresh.status()
                ));

        PlanningContextSnapshot snapshot = new PlanningContextSnapshot(
                UUID.randomUUID(),
                SCHEMA_VERSION,
                trip.id(),
                taskId,
                trip.destination(),
                trip.startDate(),
                trip.endDate(),
                generatedAt,
                stale,
                sources,
                List.copyOf(facts),
                conflicts,
                List.copyOf(excludedFacts),
                diagnostics
        );
        String sourcesJson = writeJson(sources);
        String factsJson = writeJson(facts);
        String conflictsJson = writeJson(conflicts);
        String excludedFactsJson = writeJson(excludedFacts);
        String diagnosticsJson = writeJson(diagnostics);
        String digest = sha256(writeJson(snapshot));
        int inserted = snapshotMapper.insert(new PlanningContextSnapshotRecord(
                snapshot.snapshotId(),
                trip.id(),
                taskId,
                null,
                SCHEMA_VERSION,
                trip.destination(),
                trip.startDate(),
                trip.endDate(),
                generatedAt,
                stale,
                sourcesJson,
                factsJson,
                conflictsJson,
                excludedFactsJson,
                diagnosticsJson,
                digest
        ));
        if (inserted != 1) {
            throw new IllegalStateException("Could not persist planning context snapshot");
        }
        return snapshot;
    }

    private PlanningFact toPlanningFact(TrustedFactRecord fact, Instant now) {
        boolean stale = !fact.expiresAt().isAfter(now);
        return new PlanningFact(
                fact.factId(),
                fact.category(),
                fact.statement(),
                readJson(fact.normalizedValueJson()),
                fact.evidence(),
                fact.effectiveDate(),
                fact.checkedAt(),
                fact.expiresAt(),
                stale,
                fact.sourceName(),
                fact.sourceType(),
                fact.sourceUrl(),
                fact.reliabilityLevel(),
                fact.sourceReviewed(),
                fact.hardConstraintEligible() && !stale
        );
    }

    private PlanningFact toPlanningFact(
            GuideImportService.PlanningGuideFact fact,
            Instant now
    ) {
        return new PlanningFact(
                fact.factId().toString(),
                fact.category(),
                fact.statement(),
                null,
                fact.evidence(),
                fact.effectiveDate(),
                fact.observedAt(),
                fact.expiresAt(),
                !fact.expiresAt().isAfter(now),
                fact.sourceTitle(),
                fact.sourceType(),
                fact.sourceUrl(),
                "CITY_INTELLIGENCE".equals(fact.sourceType())
                        ? "PROVIDER"
                        : "COMMUNITY",
                false,
                false
        );
    }

    private List<Source> uniqueSources(List<PlanningFact> facts) {
        Map<String, Source> sources = new LinkedHashMap<>();
        for (PlanningFact fact : facts) {
            String key = String.join(
                    "\u0000",
                    nullToEmpty(fact.sourceName()),
                    nullToEmpty(fact.sourceType()),
                    nullToEmpty(fact.sourceUrl())
            );
            sources.putIfAbsent(key, new Source(
                    fact.sourceName(),
                    fact.sourceType(),
                    fact.sourceUrl(),
                    fact.reliabilityLevel()
            ));
        }
        return List.copyOf(sources.values());
    }

    private Conflict toConflict(FactMergeDecisionRecord decision) {
        return new Conflict(
                decision.selectedFactId(),
                readJson(decision.conflictFactIdsJson()),
                readJson(decision.downgradedFactIdsJson()),
                decision.decisionReason(),
                decision.needsManualReview()
        );
    }

    private Conflict toConflict(
            PlanningFactConflictResolver.ResolvedConflict conflict
    ) {
        return new Conflict(
                conflict.selectedFactId(),
                objectMapper.valueToTree(conflict.conflictFactIds()),
                objectMapper.valueToTree(conflict.downgradedFactIds()),
                conflict.reason(),
                conflict.needsManualReview()
        );
    }

    private boolean appliesToTrip(
            LocalDate effectiveDate,
            LocalDate startDate,
            LocalDate endDate
    ) {
        return effectiveDate == null
                || !effectiveDate.isBefore(startDate) && !effectiveDate.isAfter(endDate);
    }

    private JsonNode readJson(String value) {
        try {
            return objectMapper.readTree(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored planning fact JSON is invalid", exception);
        }
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not serialize planning context", exception);
        }
    }

    private String sha256(String value) {
        try {
            return java.util.HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256")
                            .digest(value.getBytes(StandardCharsets.UTF_8))
            );
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    private String nullToEmpty(String value) {
        return value == null ? "" : value;
    }

    public record PlanningContextSnapshot(
            UUID snapshotId,
            int schemaVersion,
            UUID tripId,
            UUID planningTaskId,
            String city,
            LocalDate travelStartDate,
            LocalDate travelEndDate,
            Instant generatedAt,
            boolean stale,
            List<Source> sources,
            List<PlanningFact> facts,
            List<Conflict> conflicts,
            List<ExcludedFact> excludedFacts,
            List<Diagnostic> diagnostics
    ) {
    }

    public record PlanningFact(
            String factId,
            String category,
            String statement,
            JsonNode normalizedValue,
            String evidence,
            LocalDate effectiveDate,
            Instant checkedAt,
            Instant expiresAt,
            boolean stale,
            String sourceName,
            String sourceType,
            String sourceUrl,
            String reliabilityLevel,
            boolean sourceReviewed,
            boolean hardConstraintEligible
    ) {
    }

    public record Source(
            String sourceName,
            String sourceType,
            String sourceUrl,
            String reliabilityLevel
    ) {
    }

    public record Conflict(
            String selectedFactId,
            JsonNode conflictFactIds,
            JsonNode downgradedFactIds,
            String reason,
            boolean needsManualReview
    ) {
    }

    public record ExcludedFact(
            String factId,
            String category,
            String statement,
            String reason
    ) {
    }

    public record Diagnostic(String code, String message, String refreshStatus) {
    }
}
