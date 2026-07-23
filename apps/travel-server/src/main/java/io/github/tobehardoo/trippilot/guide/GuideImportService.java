package io.github.tobehardoo.trippilot.guide;

import java.net.URI;
import java.net.URISyntaxException;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedGuide;
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
            "COST", "QUEUE", "RESERVATION", "TIP"
    );

    private final TripService tripService;
    private final GuideIntelligenceClient intelligenceClient;
    private final GuideImportMapper mapper;
    private final GuideImportPersistenceService persistenceService;

    public GuideImportService(
            TripService tripService,
            GuideIntelligenceClient intelligenceClient,
            GuideImportMapper mapper,
            GuideImportPersistenceService persistenceService
    ) {
        this.tripService = tripService;
        this.intelligenceClient = intelligenceClient;
        this.mapper = mapper;
        this.persistenceService = persistenceService;
    }

    public GuideImportResponse create(UUID ownerId, UUID tripId, GuideImportRequest request) {
        tripService.get(ownerId, tripId);
        String sourceUrl = validateSourceUrl(request.sourceUrl());
        FetchedGuide fetched = intelligenceClient.fetch(sourceUrl);
        validateFetchedGuide(fetched);

        GuideImportRecord candidate = new GuideImportRecord(
                UUID.randomUUID(),
                tripId,
                fetched.sourceUrl(),
                fetched.finalUrl(),
                fetched.sourceHost(),
                fetched.title(),
                fetched.excerpt(),
                fetched.contentHash(),
                fetched.fetchedAt(),
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

    private GuideImportResponse toResponse(GuideImportRecord record) {
        List<GuideFactResponse> facts = mapper.findFacts(record.id()).stream()
                .map(fact -> new GuideFactResponse(
                        fact.id(),
                        fact.category(),
                        fact.statement(),
                        fact.evidence(),
                        fact.confidence(),
                        fact.observedAt(),
                        fact.expiresAt()
                ))
                .toList();
        return new GuideImportResponse(
                record.id(),
                record.sourceUrl(),
                record.finalUrl(),
                record.sourceHost(),
                record.title(),
                record.excerpt(),
                record.contentHash(),
                record.fetchedAt(),
                facts
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
                || guide.facts().stream().anyMatch(this::invalidFact)) {
            throw invalidServiceResponse();
        }
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
            String sourceUrl,
            String finalUrl,
            String sourceHost,
            String title,
            String excerpt,
            String contentHash,
            Instant fetchedAt,
            List<GuideFactResponse> facts
    ) {
    }

    public record GuideFactResponse(
            UUID id,
            String category,
            String statement,
            String evidence,
            double confidence,
            Instant observedAt,
            Instant expiresAt
    ) {
    }
}
