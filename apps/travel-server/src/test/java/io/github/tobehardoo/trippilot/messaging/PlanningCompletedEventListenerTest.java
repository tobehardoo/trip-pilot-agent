package io.github.tobehardoo.trippilot.messaging;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.planning.PlanningCompletionHandler;
import io.github.tobehardoo.trippilot.planning.PlanningEventRejectedException;
import io.github.tobehardoo.trippilot.support.PlanningCompletedEventFixture;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PlanningCompletedEventListenerTest {

    private final PlanningCompletedEventParser parser = new PlanningCompletedEventParser(
            new ObjectMapper().findAndRegisterModules()
    );

    @Test
    void passesAValidCompletedEventToTheApplicationHandler() {
        RecordingHandler handler = new RecordingHandler();
        PlanningCompletedEventListener listener = new PlanningCompletedEventListener(parser, handler);

        listener.consume(validBody());

        assertThat(handler.received).isNotNull();
        assertThat(handler.received.eventType()).isEqualTo("PLANNING_COMPLETED");
    }

    @Test
    void rejectsAnInvalidContractWithoutRequeue() {
        PlanningCompletedEventListener listener = new PlanningCompletedEventListener(
                parser, event -> { throw new AssertionError("handler must not be called"); }
        );

        assertThatThrownBy(() -> listener.consume("not-json".getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(AmqpRejectAndDontRequeueException.class)
                .hasCauseInstanceOf(PlanningEventContractException.class);
    }

    @Test
    void rejectsANonRetryableBusinessMismatchWithoutRequeue() {
        PlanningCompletedEventListener listener = new PlanningCompletedEventListener(
                parser, event -> { throw new PlanningEventRejectedException("identity mismatch"); }
        );

        assertThatThrownBy(() -> listener.consume(validBody()))
                .isInstanceOf(AmqpRejectAndDontRequeueException.class)
                .hasCauseInstanceOf(PlanningEventRejectedException.class);
    }

    @Test
    void letsInfrastructureFailuresPropagateForBrokerRedelivery() {
        PlanningCompletedEventListener listener = new PlanningCompletedEventListener(
                parser, event -> { throw new IllegalStateException("database unavailable"); }
        );

        assertThatThrownBy(() -> listener.consume(validBody()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessage("database unavailable");
    }

    private byte[] validBody() {
        return PlanningCompletedEventFixture.completedEvent(
                UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()
        ).getBytes(StandardCharsets.UTF_8);
    }

    private static final class RecordingHandler implements PlanningCompletionHandler {
        private PlanningCompletedEvent received;

        @Override
        public void handle(PlanningCompletedEvent event) {
            received = event;
        }
    }
}
