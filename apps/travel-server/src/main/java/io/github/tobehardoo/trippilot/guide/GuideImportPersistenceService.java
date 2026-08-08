package io.github.tobehardoo.trippilot.guide;

import java.util.UUID;
import java.util.List;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedFact;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedGuide;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedMergeDecision;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedModelExtraction;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedNormalizedDocument;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedRejectedFact;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedTrustedFact;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.FactMergeDecisionRecord;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.NormalizedDocumentRecord;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.RejectedFactRecord;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.TrustedFactRecord;
import io.github.tobehardoo.trippilot.trip.TripService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class GuideImportPersistenceService {

    private final TripService tripService;
    private final GuideImportMapper mapper;
    private final ObjectMapper objectMapper;

    public GuideImportPersistenceService(
            TripService tripService,
            GuideImportMapper mapper,
            ObjectMapper objectMapper
    ) {
        this.tripService = tripService;
        this.mapper = mapper;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public GuideImportRecord persist(
            UUID ownerId,
            UUID tripId,
            GuideImportRecord candidate,
            FetchedGuide fetched
    ) {
        // Ownership is checked again after the network request so a deleted or
        // transferred trip cannot receive data based on stale authorization.
        tripService.get(ownerId, tripId);
        if ("CITY_INTELLIGENCE".equals(candidate.sourceType())) {
            mapper.lockTripForCityRefresh(tripId).orElseThrow(
                    () -> new IllegalStateException("Trip disappeared during city refresh")
            );
        }
        boolean created = mapper.insertImport(candidate) == 1;
        GuideImportRecord persisted = created
                ? candidate
                : mapper.findIdentity(tripId, fetched.finalUrl(), fetched.contentHash())
                        .orElseThrow(() -> new IllegalStateException(
                                "Guide import conflict could not be resolved"
                        ));
        if (!created) {
            GuideImportRecord refreshed = new GuideImportRecord(
                    persisted.id(),
                    persisted.tripId(),
                    candidate.sourceType(),
                    candidate.sourceUrl(),
                    candidate.finalUrl(),
                    candidate.sourceHost(),
                    candidate.title(),
                    candidate.excerpt(),
                    candidate.contentHash(),
                    candidate.fetchedAt(),
                    persisted.enabled(),
                    persisted.createdAt(),
                    candidate.qualityScore()
            );
            if (mapper.refreshImport(refreshed) != 1) {
                throw new IllegalStateException("Guide import refresh could not be persisted");
            }
            persisted = refreshed;
        }
        for (FetchedFact fact : fetched.facts()) {
            mapper.upsertFact(new GuideFactRecord(
                    UUID.randomUUID(),
                    persisted.id(),
                    fact.category(),
                    fact.statement(),
                    fact.evidence(),
                    fact.confidence(),
                    fact.effectiveDate(),
                    fact.observedAt(),
                    fact.expiresAt()
            ));
        }
        persistTrustedPipeline(persisted.id(), fetched);
        if ("CITY_INTELLIGENCE".equals(candidate.sourceType())) {
            mapper.disableOtherCityImports(tripId, persisted.id());
        }
        return persisted;
    }

    private void persistTrustedPipeline(UUID guideImportId, FetchedGuide fetched) {
        FetchedNormalizedDocument document = fetched.normalizedDocument();
        if (document == null) {
            return;
        }
        FetchedModelExtraction model = fetched.modelExtraction() == null
                ? new FetchedModelExtraction(
                        "SKIPPED", 0, "MODEL_NOT_REPORTED", "No model diagnostic"
                )
                : fetched.modelExtraction();
        mapper.upsertNormalizedDocument(new NormalizedDocumentRecord(
                guideImportId,
                document.documentId(),
                document.sourceType(),
                document.sourceName(),
                document.sourceUrl(),
                document.city(),
                document.title(),
                document.content(),
                document.fetchedAt(),
                document.contentHash(),
                document.encoding(),
                document.language(),
                writeJson(document.metadata()),
                document.reliabilityLevel(),
                document.sourceReviewed(),
                model.status(),
                model.attempts(),
                model.failureCode(),
                model.failureReason()
        ));
        mapper.deactivateTrustedFacts(guideImportId);
        for (FetchedTrustedFact fact : safe(fetched.trustedFacts())) {
            mapper.upsertTrustedFact(new TrustedFactRecord(
                    guideImportId,
                    fact.factId(),
                    fact.documentId(),
                    document.city(),
                    fact.category(),
                    fact.statement(),
                    writeJson(fact.normalizedValue()),
                    fact.evidence(),
                    fact.evidenceStart(),
                    fact.evidenceEnd(),
                    fact.confidence(),
                    fact.effectiveDate(),
                    fact.checkedAt(),
                    fact.expiresAt(),
                    fact.sourceType(),
                    fact.sourceName(),
                    fact.sourceUrl(),
                    fact.reliabilityLevel(),
                    fact.sourceReviewed(),
                    fact.hardConstraintEligible()
            ));
        }
        mapper.deleteRejectedFacts(guideImportId);
        for (FetchedRejectedFact rejected : safe(fetched.rejectedFacts())) {
            mapper.insertRejectedFact(new RejectedFactRecord(
                    UUID.randomUUID(),
                    guideImportId,
                    rejected.category(),
                    rejected.statement(),
                    writeJson(rejected.reasons())
            ));
        }
        mapper.deleteFactMergeDecisions(guideImportId);
        for (FetchedMergeDecision decision : safe(fetched.factMergeDecisions())) {
            mapper.insertFactMergeDecision(new FactMergeDecisionRecord(
                    UUID.randomUUID(),
                    guideImportId,
                    decision.selectedFactId(),
                    writeJson(safe(decision.conflictFactIds())),
                    writeJson(safe(decision.downgradedFactIds())),
                    decision.reason(),
                    decision.needsManualReview()
            ));
        }
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Trusted guide data could not be serialized", exception);
        }
    }

    private <T> List<T> safe(List<T> values) {
        return values == null ? List.of() : values;
    }
}
