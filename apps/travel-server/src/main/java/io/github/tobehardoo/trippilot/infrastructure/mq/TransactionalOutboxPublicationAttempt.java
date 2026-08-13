package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.time.Clock;
import java.time.Instant;

import io.github.tobehardoo.trippilot.planning.PlanningLogContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.transaction.annotation.Transactional;

public class TransactionalOutboxPublicationAttempt implements OutboxPublicationAttempt {

    private static final Logger log = LoggerFactory.getLogger(TransactionalOutboxPublicationAttempt.class);

    private static final int MAX_ERROR_LENGTH = 500;
    private static final int MAX_ATTEMPTS = 10;
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
        try (PlanningLogContext ctx = PlanningLogContext.open()
                .put(PlanningLogContext.EVENT_ID, event.id() == null ? null : event.id().toString())
                .put(PlanningLogContext.OPERATION, event.eventType())
                .put(PlanningLogContext.RETRY_COUNT, String.valueOf(event.retryCount()))) {
            try {
                commandPublisher.publish(event);
                if (outboxMapper.markSent(event.id(), now) != 1) {
                    throw new IllegalStateException("Outbox event was not pending: " + event.id());
                }
                log.info("outbox sent: eventType={}", event.eventType());
            } catch (RuntimeException exception) {
                int retryCount = event.retryCount() + 1;
                if (retryCount > MAX_ATTEMPTS) {
                    outboxMapper.markDead(event.id(), retryCount, errorMessage(exception));
                    log.warn("outbox dead: eventType={} retryCount={} cause={}",
                            event.eventType(), retryCount, exception.getClass().getSimpleName());
                } else {
                    long delaySeconds = Math.min(1L << Math.min(event.retryCount(), 8), MAX_RETRY_DELAY_SECONDS);
                    outboxMapper.reschedule(
                            event.id(), retryCount, now.plusSeconds(delaySeconds), errorMessage(exception)
                    );
                    log.info("outbox rescheduled: eventType={} retryCount={} delaySeconds={}",
                            event.eventType(), retryCount, delaySeconds);
                }
            }
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
