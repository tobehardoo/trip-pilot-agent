package io.github.tobehardoo.trippilot.agentdialog;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.infrastructure.mq.OutboxEventRecord;
import io.github.tobehardoo.trippilot.infrastructure.mq.OutboxMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;

class AgentDialogCommandServiceTest {

    private final RecordingOutboxMapper outboxMapper = new RecordingOutboxMapper();
    private final RecordingOwnershipGuard ownershipGuard = new RecordingOwnershipGuard();
    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
    private final Clock clock = Clock.fixed(
            Instant.parse("2026-08-29T08:00:00Z"), ZoneOffset.UTC
    );
    private AgentDialogCommandService service;

    private final UUID ownerId = UUID.randomUUID();
    private final UUID tripId = UUID.randomUUID();
    private final UUID eventId = UUID.randomUUID();

    @BeforeEach
    void setUp() {
        outboxMapper.written.clear();
        ownershipGuard.calls.clear();
        ownershipGuard.failure = null;
        service = new AgentDialogCommandService(outboxMapper, ownershipGuard, objectMapper, clock);
    }

    @Test
    void startRunWritesAnAgentStartCommandThroughTheOutbox() throws Exception {
        AgentDialogCommandService.CommandQueued queued =
                service.startRun(ownerId, tripId, eventId, "十一想去成都玩");

        assertThat(queued.eventId()).isEqualTo(eventId);
        assertThat(queued.status()).isEqualTo("QUEUED");
        OutboxEventRecord record = outboxMapper.written.get(0);
        assertThat(record.routingKey()).isEqualTo("agent.start");
        assertThat(record.eventType()).isEqualTo("AGENT_START");
        assertThat(record.status()).isEqualTo("PENDING");

        JsonNode envelope = objectMapper.readTree(record.payloadJson());
        assertThat(envelope.path("eventType").asText()).isEqualTo("AGENT_START");
        assertThat(envelope.path("schemaVersion").asInt()).isEqualTo(1);
        assertThat(envelope.path("tripId").asText()).isEqualTo(tripId.toString());
        assertThat(envelope.path("userId").asText()).isEqualTo(ownerId.toString());
        assertThat(envelope.path("runId").isMissingNode()).isTrue();
        assertThat(envelope.path("payload").path("message").asText()).isEqualTo("十一想去成都玩");
    }

    @Test
    void resumeRunWritesAnAgentResumeCommandWithTheRunId() throws Exception {
        UUID runId = UUID.randomUUID();
        service.resumeRun(ownerId, tripId, runId, eventId, "就去成都");

        OutboxEventRecord record = outboxMapper.written.get(0);
        assertThat(record.routingKey()).isEqualTo("agent.resume");
        assertThat(record.eventType()).isEqualTo("AGENT_RESUME");
        JsonNode envelope = objectMapper.readTree(record.payloadJson());
        assertThat(envelope.path("runId").asText()).isEqualTo(runId.toString());
        assertThat(envelope.path("userId").isMissingNode()).isTrue();
        assertThat(envelope.path("payload").path("answer").asText()).isEqualTo("就去成都");
    }

    @Test
    void anUnownedTripIsRejected() {
        ownershipGuard.failure = new ApiException(
                HttpStatus.NOT_FOUND, "TRIP_NOT_FOUND", "no trip"
        );

        assertThatThrownBy(() -> service.startRun(ownerId, tripId, eventId, "十一想去成都玩"))
                .isInstanceOf(ApiException.class);
        assertThat(outboxMapper.written).isEmpty();
    }

    @Test
    void aBlankMessageIsRejectedWithoutWriting() {
        assertThatThrownBy(() -> service.startRun(ownerId, tripId, eventId, "   "))
                .isInstanceOf(ApiException.class)
                .extracting("status")
                .isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(outboxMapper.written).isEmpty();
    }

    @Test
    void anIdempotencyKeyReplayStillReportsQueued() {
        outboxMapper.duplicate = true;

        AgentDialogCommandService.CommandQueued queued =
                service.startRun(ownerId, tripId, eventId, "十一想去成都玩");

        assertThat(queued.status()).isEqualTo("QUEUED");
    }

    @Test
    void aFailingOutboxInsertSurfacesAsIllegalState() {
        outboxMapper.rowsWritten = 0;

        assertThatThrownBy(() -> service.startRun(ownerId, tripId, eventId, "十一想去成都玩"))
                .isInstanceOf(IllegalStateException.class);
    }

    private static final class RecordingOutboxMapper implements OutboxMapper {

        private final List<OutboxEventRecord> written = new ArrayList<>();
        private boolean duplicate;
        private int rowsWritten = 1;

        @Override
        public int insert(OutboxEventRecord event) {
            if (duplicate) {
                throw new DuplicateKeyException("duplicate outbox id");
            }
            written.add(event);
            return rowsWritten;
        }

        @Override
        public List<OutboxEventRecord> lockReadyBatch(int batchSize) {
            throw new UnsupportedOperationException();
        }

        @Override
        public int markSent(UUID id, Instant sentAt) {
            throw new UnsupportedOperationException();
        }

        @Override
        public int reschedule(UUID id, int retryCount, Instant nextAttemptAt, String lastError) {
            throw new UnsupportedOperationException();
        }

        @Override
        public int markDead(UUID id, int retryCount, String lastError) {
            throw new UnsupportedOperationException();
        }
    }

    private static final class RecordingOwnershipGuard implements TripOwnershipGuard {

        private final List<UUID> calls = new ArrayList<>();
        private ApiException failure;

        @Override
        public void requireOwnership(UUID ownerId, UUID tripId) {
            calls.add(tripId);
            if (failure != null) {
                throw failure;
            }
        }
    }
}
