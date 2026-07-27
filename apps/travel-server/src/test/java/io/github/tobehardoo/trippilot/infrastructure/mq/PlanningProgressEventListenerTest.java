package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.planning.PlanningEventRejectedException;
import io.github.tobehardoo.trippilot.planning.PlanningProgressHandler;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PlanningProgressEventListenerTest {

    private final PlanningProgressEventParser parser = new PlanningProgressEventParser(
            new ObjectMapper().findAndRegisterModules()
    );

    @Test
    void passesAValidProgressEventToTheApplicationHandler() {
        RecordingHandler handler = new RecordingHandler();
        PlanningProgressEventListener listener = new PlanningProgressEventListener(parser, handler);

        listener.consume(validBody());

        assertThat(handler.received).isNotNull();
        assertThat(handler.received.payload().stage()).isEqualTo("TASK_ACCEPTED");
    }

    @Test
    void rejectsInvalidContractsAndBusinessMismatchesWithoutRequeue() {
        PlanningProgressEventListener invalidListener = new PlanningProgressEventListener(
                parser, event -> { throw new AssertionError("handler must not be called"); }
        );
        assertThatThrownBy(() -> invalidListener.consume("not-json".getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(AmqpRejectAndDontRequeueException.class)
                .hasCauseInstanceOf(PlanningEventContractException.class);

        PlanningProgressEventListener rejectedListener = new PlanningProgressEventListener(
                parser, event -> { throw new PlanningEventRejectedException("identity mismatch"); }
        );
        assertThatThrownBy(() -> rejectedListener.consume(validBody()))
                .isInstanceOf(AmqpRejectAndDontRequeueException.class)
                .hasCauseInstanceOf(PlanningEventRejectedException.class);
    }

    private byte[] validBody() {
        return """
                {
                  "eventType":"PLANNING_PROGRESS",
                  "schemaVersion":1,
                  "eventId":"%s",
                  "traceId":"%s",
                  "taskId":"%s",
                  "tripId":"%s",
                  "occurredAt":"2026-07-27T08:00:00Z",
                  "payload":{
                    "stage":"TASK_ACCEPTED",
                    "sequence":1,
                    "progress":5,
                    "message":"Planning task accepted",
                    "statistics":{}
                  }
                }
                """.formatted(
                UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()
        ).getBytes(StandardCharsets.UTF_8);
    }

    private static final class RecordingHandler implements PlanningProgressHandler {
        private PlanningProgressEvent received;

        @Override
        public void handle(PlanningProgressEvent event) {
            received = event;
        }
    }
}
