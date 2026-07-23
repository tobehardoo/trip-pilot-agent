package io.github.tobehardoo.trippilot.guide;

import java.util.UUID;

import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedFact;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedGuide;
import io.github.tobehardoo.trippilot.trip.TripService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class GuideImportPersistenceService {

    private final TripService tripService;
    private final GuideImportMapper mapper;

    public GuideImportPersistenceService(TripService tripService, GuideImportMapper mapper) {
        this.tripService = tripService;
        this.mapper = mapper;
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
                    candidate.sourceUrl(),
                    candidate.finalUrl(),
                    candidate.sourceHost(),
                    candidate.title(),
                    candidate.excerpt(),
                    candidate.contentHash(),
                    candidate.fetchedAt(),
                    persisted.enabled(),
                    persisted.createdAt()
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
                    fact.observedAt(),
                    fact.expiresAt()
            ));
        }
        return persisted;
    }
}
