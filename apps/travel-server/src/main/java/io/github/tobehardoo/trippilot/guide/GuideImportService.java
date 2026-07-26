package io.github.tobehardoo.trippilot.guide;

import java.net.URI;
import java.net.URISyntaxException;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedMergeDecision;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedModelExtraction;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedNormalizedDocument;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedRejectedFact;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedTrustedFact;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedGuide;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.FactMergeDecisionRecord;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.NormalizedDocumentRecord;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.RejectedFactRecord;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.TrustedFactRecord;
import io.github.tobehardoo.trippilot.trip.TripService;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class GuideImportService {

    private static final int MAX_FACTS = 100;
    private static final int MAX_FACT_TEXT_LENGTH = 1_000;
    private static final Set<String> FACT_CATEGORIES = Set.of(
            "ATTRACTION", "DINING", "TRANSPORT", "TIMING",
            "COST", "QUEUE", "RESERVATION", "LOCATION", "WEATHER", "TIP"
    );
    private static final Set<String> SOURCE_TYPES = Set.of(
            "PUBLIC_GUIDE_URL", "PASTED_TEXT", "TEXT_FILE",
            "XIAOHONGSHU_SHARED_TEXT", "CITY_INTELLIGENCE"
    );
    private static final Set<String> TRUSTED_FACT_CATEGORIES = Set.of(
            "ADDRESS", "COORDINATES", "OPENING_HOURS", "TEMPORARY_CLOSURE",
            "TICKET_PRICE", "REFERENCE_SPEND", "RESERVATION_REQUIREMENT",
            "RESERVATION_ENTRY", "TRANSPORT_ADVICE", "WEATHER",
            "VENUE_ENVIRONMENT", "ATTRACTION_IDENTITY"
    );
    private static final Set<String> OFFICIAL_RELIABILITY = Set.of(
            "OFFICIAL_ATTRACTION", "OFFICIAL_TOURISM"
    );
    private static final Set<String> STRONG_FACTS = Set.of(
            "OPENING_HOURS", "TEMPORARY_CLOSURE",
            "TICKET_PRICE", "RESERVATION_REQUIREMENT"
    );

    private final TripService tripService;
    private final GuideIntelligenceClient intelligenceClient;
    private final GuideImportMapper mapper;
    private final GuideImportPersistenceService persistenceService;
    private final ObjectMapper objectMapper;

    public GuideImportService(
            TripService tripService,
            GuideIntelligenceClient intelligenceClient,
            GuideImportMapper mapper,
            GuideImportPersistenceService persistenceService,
            ObjectMapper objectMapper
    ) {
        this.tripService = tripService;
        this.intelligenceClient = intelligenceClient;
        this.mapper = mapper;
        this.persistenceService = persistenceService;
        this.objectMapper = objectMapper;
    }

    public GuideImportResponse create(UUID ownerId, UUID tripId, GuideImportRequest request) {
        TripService.TripResponse trip = tripService.get(ownerId, tripId);
        String sourceType = request.normalizedSourceType();
        GuideImportRequest normalizedRequest;
        if ("PUBLIC_GUIDE_URL".equals(sourceType)) {
            normalizedRequest = new GuideImportRequest(
                    validateSourceUrl(request.sourceUrl()),
                    sourceType,
                    null,
                    null,
                    null,
                    null,
                    null
            );
        } else if ("CITY_INTELLIGENCE".equals(sourceType)) {
            normalizedRequest = new GuideImportRequest(
                    null,
                    sourceType,
                    null,
                    null,
                    trip.destination(),
                    trip.startDate(),
                    trip.endDate()
            );
        } else {
            normalizedRequest = new GuideImportRequest(
                    null,
                    sourceType,
                    request.title().trim(),
                    request.content().trim(),
                    null,
                    null,
                    null
            );
        }
        FetchedGuide fetched = intelligenceClient.fetch(normalizedRequest);
        validateFetchedGuide(fetched);

        GuideImportRecord candidate = new GuideImportRecord(
                UUID.randomUUID(),
                tripId,
                fetched.sourceType(),
                fetched.sourceUrl(),
                fetched.finalUrl(),
                fetched.sourceHost(),
                fetched.title(),
                fetched.excerpt(),
                fetched.contentHash(),
                fetched.fetchedAt(),
                true,
                null
        );
        GuideImportRecord persisted = persistenceService.persist(
                ownerId,
                tripId,
                candidate,
                fetched
        );
        return toResponse(persisted);
    }

    @Transactional(readOnly = true)
    public List<GuideImportResponse> list(UUID ownerId, UUID tripId) {
        tripService.get(ownerId, tripId);
        return mapper.findAllOwned(tripId, ownerId).stream().map(this::toResponse).toList();
    }

    @Transactional
    public GuideImportResponse setEnabled(
            UUID ownerId,
            UUID tripId,
            UUID guideImportId,
            boolean enabled
    ) {
        tripService.get(ownerId, tripId);
        if (mapper.updateEnabled(guideImportId, tripId, ownerId, enabled) != 1) {
            throw new ApiException(
                    HttpStatus.NOT_FOUND,
                    "GUIDE_IMPORT_NOT_FOUND",
                    "Guide import was not found"
            );
        }
        return mapper.findOwnedById(guideImportId, tripId, ownerId)
                .map(this::toResponse)
                .orElseThrow(() -> new IllegalStateException(
                        "Updated guide import could not be read"
                ));
    }

    @Transactional(readOnly = true)
    public List<PlanningGuideFact> planningEvidence(
            UUID ownerId,
            UUID tripId,
            Instant asOf
    ) {
        tripService.get(ownerId, tripId);
        return mapper.findFreshPlanningEvidence(tripId, ownerId, asOf).stream()
                .map(record -> new PlanningGuideFact(
                        record.guideImportId(),
                        record.factId(),
                        record.category(),
                        record.statement(),
                        record.evidence(),
                        record.sourceType(),
                        record.sourceUrl(),
                        record.sourceHost(),
                        record.sourceTitle(),
                        record.confidence(),
                        record.effectiveDate(),
                        record.observedAt(),
                        record.expiresAt()
                ))
                .toList();
    }

    private GuideImportResponse toResponse(GuideImportRecord record) {
        List<GuideFactResponse> facts = mapper.findFacts(record.id()).stream()
                .map(fact -> new GuideFactResponse(
                        fact.id(),
                        fact.category(),
                        fact.statement(),
                        fact.evidence(),
                        fact.confidence(),
                        fact.effectiveDate(),
                        fact.observedAt(),
                        fact.expiresAt()
                ))
                .toList();
        NormalizedDocumentResponse normalizedDocument = mapper.findNormalizedDocument(record.id())
                .map(this::toNormalizedDocumentResponse)
                .orElse(null);
        List<TrustedFactResponse> trustedFacts = mapper.findTrustedFacts(record.id())
                .stream()
                .map(this::toTrustedFactResponse)
                .toList();
        List<RejectedFactResponse> rejectedFacts = mapper.findRejectedFacts(record.id())
                .stream()
                .map(this::toRejectedFactResponse)
                .toList();
        List<FactMergeDecisionResponse> mergeDecisions =
                mapper.findFactMergeDecisions(record.id()).stream()
                        .map(this::toMergeDecisionResponse)
                        .toList();
        return new GuideImportResponse(
                record.id(),
                record.sourceType(),
                record.sourceUrl(),
                record.finalUrl(),
                record.sourceHost(),
                record.title(),
                record.excerpt(),
                record.contentHash(),
                record.fetchedAt(),
                record.enabled(),
                facts,
                normalizedDocument,
                trustedFacts,
                rejectedFacts,
                mergeDecisions,
                normalizedDocument == null ? null : normalizedDocument.modelExtraction()
        );
    }

    private String validateSourceUrl(String rawUrl) {
        try {
            URI uri = new URI(rawUrl.trim());
            if (!"https".equals(uri.getScheme())
                    || uri.getHost() == null
                    || uri.getUserInfo() != null
                    || uri.getPort() != -1 && uri.getPort() != 443
                    || "localhost".equals(uri.getHost().toLowerCase(Locale.ROOT))) {
                throw invalidUrl();
            }
            return uri.normalize().toASCIIString();
        } catch (URISyntaxException exception) {
            throw invalidUrl();
        }
    }

    private void validateFetchedGuide(FetchedGuide guide) {
        if (guide == null
                || guide.facts() == null
                || guide.facts().size() > MAX_FACTS
                || !SOURCE_TYPES.contains(guide.sourceType())
                || invalidText(guide.sourceUrl(), 2_048)
                || invalidText(guide.finalUrl(), 2_048)
                || invalidText(guide.sourceHost(), 253)
                || guide.title() == null
                || guide.title().isBlank()
                || guide.title().length() > 300
                || guide.excerpt() == null
                || guide.excerpt().length() > 800
                || guide.contentHash() == null
                || !guide.contentHash().matches("[a-f0-9]{64}")
                || guide.fetchedAt() == null
                || guide.facts().stream().anyMatch(this::invalidFact)
                || invalidTrustedPipeline(guide)) {
            throw invalidServiceResponse();
        }
    }

    private boolean invalidTrustedPipeline(FetchedGuide guide) {
        FetchedNormalizedDocument document = guide.normalizedDocument();
        List<FetchedTrustedFact> trustedFacts = safe(guide.trustedFacts());
        List<FetchedRejectedFact> rejectedFacts = safe(guide.rejectedFacts());
        List<FetchedMergeDecision> decisions = safe(guide.factMergeDecisions());
        if (document == null) {
            return !trustedFacts.isEmpty() || !rejectedFacts.isEmpty() || !decisions.isEmpty();
        }
        FetchedModelExtraction model = guide.modelExtraction();
        if (invalidText(document.documentId(), 40)
                || !document.documentId().matches("doc_[a-f0-9]{32}")
                || invalidText(document.sourceType(), 60)
                || invalidText(document.sourceName(), 300)
                || invalidText(document.city(), 120)
                || invalidText(document.title(), 300)
                || invalidText(document.content(), 100_000)
                || document.fetchedAt() == null
                || document.contentHash() == null
                || !document.contentHash().matches("[a-f0-9]{64}")
                || invalidText(document.encoding(), 80)
                || invalidText(document.language(), 40)
                || document.metadata() == null
                || invalidText(document.reliabilityLevel(), 40)
                || model == null
                || !Set.of("EXTRACTED", "SKIPPED", "FAILED").contains(model.status())
                || model.attempts() < 0
                || trustedFacts.size() > MAX_FACTS
                || rejectedFacts.size() > MAX_FACTS
                || decisions.size() > MAX_FACTS) {
            return true;
        }
        Set<String> factIds = trustedFacts.stream()
                .map(FetchedTrustedFact::factId)
                .collect(java.util.stream.Collectors.toSet());
        return trustedFacts.stream().anyMatch(fact -> invalidTrustedFact(document, fact))
                || rejectedFacts.stream().anyMatch(this::invalidRejectedFact)
                || decisions.stream().anyMatch(decision -> invalidMergeDecision(
                        decision, factIds
                ));
    }

    private boolean invalidTrustedFact(
            FetchedNormalizedDocument document,
            FetchedTrustedFact fact
    ) {
        if (fact == null
                || invalidText(fact.factId(), 40)
                || !fact.factId().matches("fact_[a-f0-9]{32}")
                || !document.documentId().equals(fact.documentId())
                || !TRUSTED_FACT_CATEGORIES.contains(fact.category())
                || invalidText(fact.statement(), 2_000)
                || fact.normalizedValue() == null
                || invalidText(fact.evidence(), 2_000)
                || fact.evidenceStart() < 0
                || fact.evidenceEnd() <= fact.evidenceStart()
                || fact.evidenceEnd() > document.content().length()
                || !Double.isFinite(fact.confidence())
                || fact.confidence() < 0
                || fact.confidence() > 1
                || fact.checkedAt() == null
                || fact.expiresAt() == null
                || !fact.expiresAt().isAfter(fact.checkedAt())
                || invalidText(fact.sourceType(), 60)
                || invalidText(fact.sourceName(), 300)
                || invalidText(fact.reliabilityLevel(), 40)) {
            return true;
        }
        String evidence = document.content().substring(
                fact.evidenceStart(), fact.evidenceEnd()
        );
        if (!evidence.equals(fact.evidence())) {
            return true;
        }
        boolean official = OFFICIAL_RELIABILITY.contains(fact.reliabilityLevel());
        if (official && !fact.sourceReviewed()) {
            return true;
        }
        return fact.hardConstraintEligible()
                && (!official || !fact.sourceReviewed() || !STRONG_FACTS.contains(fact.category()));
    }

    private boolean invalidRejectedFact(FetchedRejectedFact rejected) {
        return rejected == null
                || invalidText(rejected.category(), 60)
                || invalidText(rejected.statement(), 2_000)
                || rejected.reasons() == null
                || rejected.reasons().isEmpty()
                || rejected.reasons().size() > 20
                || rejected.reasons().stream().anyMatch(reason -> reason == null
                        || invalidText(reason.code(), 80)
                        || invalidText(reason.message(), 500));
    }

    private boolean invalidMergeDecision(
            FetchedMergeDecision decision,
            Set<String> factIds
    ) {
        return decision == null
                || !factIds.contains(decision.selectedFactId())
                || decision.conflictFactIds() == null
                || decision.downgradedFactIds() == null
                || !factIds.containsAll(decision.conflictFactIds())
                || !factIds.containsAll(decision.downgradedFactIds())
                || invalidText(decision.reason(), 1_000);
    }

    private boolean invalidFact(GuideIntelligenceClient.FetchedFact fact) {
        return fact == null
                || !FACT_CATEGORIES.contains(fact.category())
                || invalidText(fact.statement(), MAX_FACT_TEXT_LENGTH)
                || invalidText(fact.evidence(), MAX_FACT_TEXT_LENGTH)
                || !Double.isFinite(fact.confidence())
                || fact.confidence() < 0
                || fact.confidence() > 1
                || fact.observedAt() == null
                || fact.expiresAt() == null
                || !fact.expiresAt().isAfter(fact.observedAt());
    }

    private boolean invalidText(String value, int maximumLength) {
        return value == null || value.isBlank() || value.length() > maximumLength;
    }

    private NormalizedDocumentResponse toNormalizedDocumentResponse(
            NormalizedDocumentRecord document
    ) {
        return new NormalizedDocumentResponse(
                document.documentId(),
                document.sourceType(),
                document.sourceName(),
                document.sourceUrl(),
                document.city(),
                document.title(),
                document.contentHash(),
                document.fetchedAt(),
                document.encoding(),
                document.language(),
                readJson(document.metadataJson()),
                document.reliabilityLevel(),
                document.sourceReviewed(),
                new ModelExtractionResponse(
                        document.modelStatus(),
                        document.modelAttempts(),
                        document.modelFailureCode(),
                        document.modelFailureReason()
                )
        );
    }

    private TrustedFactResponse toTrustedFactResponse(TrustedFactRecord fact) {
        return new TrustedFactResponse(
                fact.factId(),
                fact.documentId(),
                fact.category(),
                fact.statement(),
                readJson(fact.normalizedValueJson()),
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
        );
    }

    private RejectedFactResponse toRejectedFactResponse(RejectedFactRecord rejected) {
        return new RejectedFactResponse(
                rejected.category(),
                rejected.statement(),
                readJson(rejected.reasonsJson())
        );
    }

    private FactMergeDecisionResponse toMergeDecisionResponse(
            FactMergeDecisionRecord decision
    ) {
        return new FactMergeDecisionResponse(
                decision.selectedFactId(),
                readJson(decision.conflictFactIdsJson()),
                readJson(decision.downgradedFactIdsJson()),
                decision.decisionReason(),
                decision.needsManualReview()
        );
    }

    private JsonNode readJson(String value) {
        try {
            return objectMapper.readTree(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored trusted guide JSON is invalid", exception);
        }
    }

    private <T> List<T> safe(List<T> values) {
        return values == null ? List.of() : values;
    }

    private ApiException invalidServiceResponse() {
        return new ApiException(
                HttpStatus.BAD_GATEWAY,
                "GUIDE_SERVICE_INVALID_RESPONSE",
                "Guide intelligence service returned an invalid response"
        );
    }

    private ApiException invalidUrl() {
        return new ApiException(
                HttpStatus.BAD_REQUEST,
                "GUIDE_URL_INVALID",
                "Guide URL must be a public HTTPS URL"
        );
    }

    public record GuideImportResponse(
            UUID id,
            String sourceType,
            String sourceUrl,
            String finalUrl,
            String sourceHost,
            String title,
            String excerpt,
            String contentHash,
            Instant fetchedAt,
            boolean enabled,
            List<GuideFactResponse> facts,
            NormalizedDocumentResponse normalizedDocument,
            List<TrustedFactResponse> trustedFacts,
            List<RejectedFactResponse> rejectedFacts,
            List<FactMergeDecisionResponse> factMergeDecisions,
            ModelExtractionResponse modelExtraction
    ) {
    }

    public record NormalizedDocumentResponse(
            String documentId,
            String sourceType,
            String sourceName,
            String sourceUrl,
            String city,
            String title,
            String contentHash,
            Instant fetchedAt,
            String encoding,
            String language,
            JsonNode metadata,
            String reliabilityLevel,
            boolean sourceReviewed,
            ModelExtractionResponse modelExtraction
    ) {
    }

    public record TrustedFactResponse(
            String factId,
            String documentId,
            String category,
            String statement,
            JsonNode normalizedValue,
            String evidence,
            int evidenceStart,
            int evidenceEnd,
            double confidence,
            LocalDate effectiveDate,
            Instant checkedAt,
            Instant expiresAt,
            String sourceType,
            String sourceName,
            String sourceUrl,
            String reliabilityLevel,
            boolean sourceReviewed,
            boolean hardConstraintEligible
    ) {
    }

    public record RejectedFactResponse(
            String category,
            String statement,
            JsonNode reasons
    ) {
    }

    public record FactMergeDecisionResponse(
            String selectedFactId,
            JsonNode conflictFactIds,
            JsonNode downgradedFactIds,
            String reason,
            boolean needsManualReview
    ) {
    }

    public record ModelExtractionResponse(
            String status,
            int attempts,
            String failureCode,
            String failureReason
    ) {
    }

    public record GuideFactResponse(
            UUID id,
            String category,
            String statement,
            String evidence,
            double confidence,
            LocalDate effectiveDate,
            Instant observedAt,
            Instant expiresAt
    ) {
    }

    public record PlanningGuideFact(
            UUID guideImportId,
            UUID factId,
            String category,
            String statement,
            String evidence,
            String sourceType,
            String sourceUrl,
            String sourceHost,
            String sourceTitle,
            double confidence,
            LocalDate effectiveDate,
            Instant observedAt,
            Instant expiresAt
    ) {
    }
}
