package io.github.tobehardoo.trippilot.messaging;

import java.time.Clock;
import java.time.Instant;

import org.springframework.transaction.annotation.Transactional;

public class TransactionalOutboxPublicationAttempt implements OutboxPublicationAttempt {

    private static final int MAX_ERROR_LENGTH = 500;
    private static final long MAX_RETRY_DELAY_SECONDS = 300;

    private final OutboxMapper outboxMapper;
    private final PlanningCommandPublisher commandPublisher;
    private final Clock clock;

    public TransactionalOutboxPublicationAttempt(OutboxMapper outboxMapper,
                                                 PlanningCommandPublisher commandPublisher,
                                                 Clock clock) {
        this.outboxMapper = outboxMapper;
        this.commandPublisher = commandPublisher;
        this.clock = clock;
    }

    @Override
    @Transactional
    public boolean publishNext() {
        var events = outboxMapper.lockReadyBatch(1);
        if (events.isEmpty()) {
            return false;
        }
        publishOne(events.getFirst());
        return true;
    }

    private void publishOne(OutboxEventRecord event) {
        Instant now = clock.instant();
        try {
            commandPublisher.publish(event);
            if (outboxMapper.markSent(event.id(), now) != 1) {
                throw new IllegalStateException("Outbox event was not pending: " + event.id());
            }
        } catch (RuntimeException exception) {
            int retryCount = event.retryCount() + 1;
            long delaySeconds = Math.min(1L << Math.min(event.retryCount(), 8), MAX_RETRY_DELAY_SECONDS);
            outboxMapper.reschedule(
                    event.id(), retryCount, now.plusSeconds(delaySeconds), errorMessage(exception)
            );
        }
    }

    private String errorMessage(RuntimeException exception) {
        String message = exception.getMessage();
        if (message == null || message.isBlank()) {
            message = exception.getClass().getSimpleName();
        }
        return message.substring(0, Math.min(message.length(), MAX_ERROR_LENGTH));
    }
}
