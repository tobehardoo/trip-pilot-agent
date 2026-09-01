package io.github.tobehardoo.trippilot.itinerary;

import java.util.List;
import java.util.UUID;

import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent;
import org.springframework.stereotype.Component;

/**
 * Single canonical implementation for persisting knowledge evidence
 * and copying it between itinerary versions.
 *
 * Previously the same logic was duplicated in three places:
 * {@code PlanningCompletionService.persistKnowledge()},
 * {@code PlanningCompletionService.copyKnowledge()}, and
 * {@code ItineraryService.copyKnowledge()}.
 * Consolidating here ensures that all three call sites (CREATE,
 * REPLAN, and USER_EDIT) share the same persistence rules.
 */
@Component
public class ItineraryVersionPersister {

    private final ItineraryMapper itineraryMapper;

    public ItineraryVersionPersister(ItineraryMapper itineraryMapper) {
        this.itineraryMapper = itineraryMapper;
    }

    // --- write fresh knowledge (CREATE path) ---------------------------------

    public void persistKnowledge(
            UUID versionId,
            PlanningCompletedEvent.KnowledgeEvidence knowledge,
            String operationLabel
    ) {
        if (knowledge == null) {
            return;
        }
        PlanningCompletedEvent.KnowledgeFreshness freshness = knowledge.freshness();
        requireOne(
                itineraryMapper.insertKnowledge(new ItineraryMapper.KnowledgeWrite(
                        versionId, knowledge.status(), knowledge.query().strip(),
                        freshness.status(), freshness.checkedAt(),
                        freshness.staleReason(), knowledge.message()
                )),
                operationLabel
        );
        for (int index = 0; index < knowledge.citations().size(); index++) {
            PlanningCompletedEvent.KnowledgeCitation citation =
                    knowledge.citations().get(index);
            requireOne(
                    itineraryMapper.insertKnowledgeCitation(
                            new ItineraryMapper.KnowledgeCitationWrite(
                                    UUID.randomUUID(), versionId, index,
                                    citation.documentId(), citation.documentVersion(),
                                    citation.chunkId(), citation.chunkIndex(),
                                    citation.title().strip(), citation.sourceUrl(),
                                    citation.sourceName().strip(),
                                    citation.collectedAt(), citation.reliabilityLevel(),
                                    citation.similarity()
                            )
                    ),
                    operationLabel + " citation"
            );
        }
    }

    // --- clone knowledge from an existing version (REPLAN / USER_EDIT) ------

    public void copyKnowledge(
            UUID sourceVersionId,
            UUID targetVersionId,
            String operationLabel
    ) {
        itineraryMapper.findKnowledge(sourceVersionId).ifPresent(knowledge -> {
            requireOne(
                    itineraryMapper.insertKnowledge(new ItineraryMapper.KnowledgeWrite(
                            targetVersionId, knowledge.status(), knowledge.query(),
                            knowledge.freshnessStatus(), knowledge.freshnessCheckedAt(),
                            knowledge.staleReason(), knowledge.message()
                    )),
                    operationLabel
            );
            List<ItineraryMapper.StoredKnowledgeCitation> citations =
                    itineraryMapper.findKnowledgeCitations(sourceVersionId);
            for (int index = 0; index < citations.size(); index++) {
                ItineraryMapper.StoredKnowledgeCitation citation =
                        citations.get(index);
                requireOne(
                        itineraryMapper.insertKnowledgeCitation(
                                new ItineraryMapper.KnowledgeCitationWrite(
                                        UUID.randomUUID(), targetVersionId, index,
                                        citation.documentId(),
                                        citation.documentVersion(),
                                        citation.chunkId(), citation.chunkIndex(),
                                        citation.title(), citation.sourceUrl(),
                                        citation.sourceName(), citation.collectedAt(),
                                        citation.reliabilityLevel(),
                                        citation.similarity()
                                )
                        ),
                        operationLabel + " citation"
                );
            }
        });
    }

    private static void requireOne(int updatedRows, String operation) {
        if (updatedRows != 1) {
            throw new IllegalStateException(
                    "Could not persist " + operation
            );
        }
    }
}
