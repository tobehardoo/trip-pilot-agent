package io.github.tobehardoo.trippilot.messaging;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class OutboxPublicationServiceTest {

    private static final Instant NOW = Instant.parse("2026-07-14T03:00:00Z");
    private static final Clock CLOCK = Clock.fixed(NOW, ZoneOffset.UTC);

    @Test
    void marksAnEventSentOnlyAfterThePublisherReturnsSuccessfully() {
        OutboxEventRecord event = event(0);
        FakeOutboxMapper mapper = new FakeOutboxMapper(List.of(event));
        List<UUID> published = new ArrayList<>();
        TransactionalOutboxPublicationAttempt attempt = new TransactionalOutboxPublicationAttempt(
                mapper, publishedEvent -> published.add(publishedEvent.id()), CLOCK
        );

        boolean processed = attempt.publishNext();

        assertThat(processed).isTrue();
        assertThat(mapper.requestedBatchSizes).containsExactly(1);
        assertThat(published).containsExactly(event.id());
        assertThat(mapper.sentAt).containsEntry(event.id(), NOW);
        assertThat(mapper.retries).isEmpty();
    }

    @Test
    void reschedulesAFailureWithinItsSingleEventAttempt() {
        OutboxEventRecord failing = event(3);
        FakeOutboxMapper mapper = new FakeOutboxMapper(List.of(failing));
        String longMessage = "broker unavailable " + "x".repeat(600);
        TransactionalOutboxPublicationAttempt attempt = new TransactionalOutboxPublicationAttempt(
                mapper, event -> { throw new IllegalStateException(longMessage); }, CLOCK
        );

        boolean processed = attempt.publishNext();

        assertThat(processed).isTrue();
        assertThat(mapper.requestedBatchSizes).containsExactly(1);
        assertThat(mapper.sentAt).isEmpty();
        RetryUpdate retry = mapper.retries.get(failing.id());
        assertThat(retry.retryCount()).isEqualTo(4);
        assertThat(retry.nextAttemptAt()).isEqualTo(NOW.plusSeconds(8));
        assertThat(retry.lastError()).hasSize(500).startsWith("broker unavailable");
    }

    @Test
    void batchOrchestratorContinuesUntilNoEventIsReady() {
        AtomicInteger calls = new AtomicInteger();
        OutboxPublicationService service = new OutboxPublicationService(
                () -> calls.getAndIncrement() < 2
        );

        int processed = service.publishBatch();

        assertThat(processed).isEqualTo(2);
        assertThat(calls).hasValue(3);
    }

    @Test
    void batchOrchestratorCapsWorkPerScheduledRun() {
        AtomicInteger calls = new AtomicInteger();
        OutboxPublicationService service = new OutboxPublicationService(() -> {
            calls.incrementAndGet();
            return true;
        });

        int processed = service.publishBatch();

        assertThat(processed).isEqualTo(50);
        assertThat(calls).hasValue(50);
    }

    private OutboxEventRecord event(int retryCount) {
        return new OutboxEventRecord(
                UUID.randomUUID(), "PLANNING_TASK", UUID.randomUUID(),
                "PLANNING_CREATE_REQUESTED", "planning.create", "{}", "PENDING",
                retryCount, NOW, null, NOW, null
        );
    }

    private record RetryUpdate(int retryCount, Instant nextAttemptAt, String lastError) {
    }

    private static final class FakeOutboxMapper implements OutboxMapper {

        private final List<OutboxEventRecord> ready;
        private final List<Integer> requestedBatchSizes = new ArrayList<>();
        private final Map<UUID, Instant> sentAt = new HashMap<>();
        private final Map<UUID, RetryUpdate> retries = new HashMap<>();

        private FakeOutboxMapper(List<OutboxEventRecord> ready) {
            this.ready = ready;
        }

        @Override
        public int insert(OutboxEventRecord event) {
            throw new UnsupportedOperationException("Not needed by this test");
        }

        @Override
        public List<OutboxEventRecord> lockReadyBatch(int batchSize) {
            requestedBatchSizes.add(batchSize);
            return ready.stream().limit(batchSize).toList();
        }

        @Override
        public int markSent(UUID id, Instant sentAt) {
            this.sentAt.put(id, sentAt);
            return 1;
        }

        @Override
        public int reschedule(UUID id, int retryCount, Instant nextAttemptAt, String lastError) {
            retries.put(id, new RetryUpdate(retryCount, nextAttemptAt, lastError));
            return 1;
        }
    }
}
