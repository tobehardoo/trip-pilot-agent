package io.github.tobehardoo.trippilot.agentdialog;

import java.time.Clock;
import java.time.Instant;
import java.util.UUID;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.EventRejectedException;
import io.github.tobehardoo.trippilot.infrastructure.mq.AgentAskUserEvent;
import io.github.tobehardoo.trippilot.persistence.PersistenceSupport;
import io.github.tobehardoo.trippilot.infrastructure.mq.AgentCompletedEvent;
import io.github.tobehardoo.trippilot.infrastructure.mq.AgentRunFinishedEvent;
import io.github.tobehardoo.trippilot.infrastructure.mq.AgentStepEvent;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AgentDialogEventService implements AgentDialogEventHandler {

    private final AgentDialogMessageMapper messageMapper;
    private final ObjectMapper objectMapper;
    private final Clock clock;
    private final ApplicationEventPublisher eventPublisher;

    AgentDialogEventService(
            AgentDialogMessageMapper messageMapper,
            ObjectMapper objectMapper,
            Clock clock,
            ApplicationEventPublisher eventPublisher
    ) {
        this.messageMapper = messageMapper;
        this.objectMapper = objectMapper;
        this.clock = clock;
        this.eventPublisher = eventPublisher;
    }

    @Transactional
    @Override
    public void handleAskUser(AgentAskUserEvent event) {
        persist(
                event.eventId(), event.tripId(), event.runId(),
                event.eventType(), event.schemaVersion(), event.payload()
        );
    }

    @Transactional
    @Override
    public void handleStep(AgentStepEvent event) {
        persist(
                event.eventId(), event.tripId(), event.runId(),
                event.eventType(), event.schemaVersion(), event.payload()
        );
    }

    @Transactional
    @Override
    public void handleCompleted(AgentCompletedEvent event) {
        persist(
                event.eventId(), event.tripId(), event.runId(),
                event.eventType(), event.schemaVersion(), event.payload()
        );
    }

    @Transactional
    @Override
    public void handleRunFinished(AgentRunFinishedEvent event) {
        persist(
                event.eventId(), event.tripId(), event.runId(),
                event.eventType(), event.schemaVersion(), event.payload()
        );
    }

    private void persist(
            UUID eventId,
            UUID tripId,
            UUID runId,
            String eventType,
            int schemaVersion,
            Object payload
    ) {
        var existing = messageMapper.findByEventId(eventId);
        if (existing.isPresent()) {
            AgentDialogMessageRecord stored = existing.get();
            if (stored.tripId().equals(tripId) && stored.runId().equals(runId)
                    && stored.eventType().equals(eventType)) {
                // Redelivery of the same dialog event — the consumer-side
                // idempotency promised by the P2.1 resume semantics.
                return;
            }
            throw new EventRejectedException(
                    "eventId already belongs to another agent dialog message"
            );
        }
        AgentDialogMessageRecord record = new AgentDialogMessageRecord(
                null,
                eventId,
                tripId,
                runId,
                eventType,
                schemaVersion,
                writeJson(payload),
                Instant.now(clock)
        );
        if (messageMapper.insert(record) != 1) {
            throw new IllegalStateException("Could not persist agent dialog event");
        }
        AgentDialogMessageRecord persisted = messageMapper.findByEventId(eventId)
                .orElseThrow(() -> new IllegalStateException("Agent dialog event could not be read"));
        eventPublisher.publishEvent(new AgentDialogEventCreated(persisted));
    }

    private String writeJson(Object value) {
        return PersistenceSupport.writeJson(objectMapper, value, "agent dialog event");
    }
}
