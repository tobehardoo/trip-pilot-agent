package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.nio.charset.StandardCharsets;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.planning.PlanningEventRejectedException;
import io.github.tobehardoo.trippilot.planning.PlanningReviewHandler;
import io.github.tobehardoo.trippilot.support.PlanningCompletedEventFixture;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PlanningReviewRequiredEventListenerTest {

    private final PlanningReviewRequiredEventParser parser =
            new PlanningReviewRequiredEventParser(new ObjectMapper().findAndRegisterModules());

    @Test
    void passesAValidReviewEventToTheApplicationHandler() {
        RecordingHandler handler = new RecordingHandler();
        PlanningReviewRequiredEventListener listener =
                new PlanningReviewRequiredEventListener(parser, handler);

        listener.consume(validBody());

        assertThat(handler.received).isNotNull();
        assertThat(handler.received.eventType()).isEqualTo("PLANNING_REVIEW_REQUIRED");
        assertThat(handler.received.payload().status()).isEqualTo("WAITING_USER");
    }

    @Test
    void rejectsAnInvalidContractWithoutRequeue() {
        PlanningReviewRequiredEventListener listener = new PlanningReviewRequiredEventListener(
                parser, event -> { throw new AssertionError("handler must not be called"); }
        );

        assertThatThrownBy(() -> listener.consume("not-json".getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(AmqpRejectAndDontRequeueException.class)
                .hasCauseInstanceOf(PlanningEventContractException.class);
    }

    @Test
    void rejectsANonRetryableBusinessMismatchWithoutRequeue() {
        PlanningReviewRequiredEventListener listener = new PlanningReviewRequiredEventListener(
                parser, event -> { throw new PlanningEventRejectedException("identity mismatch"); }
        );

        assertThatThrownBy(() -> listener.consume(validBody()))
                .isInstanceOf(AmqpRejectAndDontRequeueException.class)
                .hasCauseInstanceOf(PlanningEventRejectedException.class);
    }

    @Test
    void letsInfrastructureFailuresPropagateForBrokerRedelivery() {
        PlanningReviewRequiredEventListener listener = new PlanningReviewRequiredEventListener(
                parser, event -> { throw new IllegalStateException("database unavailable"); }
        );

        assertThatThrownBy(() -> listener.consume(validBody()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("database unavailable");
    }

    private byte[] validBody() {
        return PlanningCompletedEventFixture.sharedReviewV1Fixture(
                "review-v1-unverified-demo.json"
        ).getBytes(StandardCharsets.UTF_8);
    }

    private static final class RecordingHandler implements PlanningReviewHandler {
        private PlanningReviewRequiredEvent received;

        @Override
        public void handle(PlanningReviewRequiredEvent event) {
            this.received = event;
        }
    }
}
