package io.github.tobehardoo.trippilot.infrastructure.mq;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.agentdialog.AgentDialogEventHandler;
import io.github.tobehardoo.trippilot.common.EventContractException;
import io.github.tobehardoo.trippilot.support.AgentEventFixtures;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;

class AgentDialogEventListenerTest {

    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
    private final RecordingHandler handler = new RecordingHandler();
    private final AgentDialogEventListener listener = new AgentDialogEventListener(
            objectMapper,
            new AgentAskUserEventParser(objectMapper),
            new AgentStepEventParser(objectMapper),
            new AgentCompletedEventParser(objectMapper),
            new AgentRunFinishedEventParser(objectMapper),
            handler
    );

    @Test
    void dispatchesAnAskUserEventToTheHandler() {
        listener.consume(eventBody("AGENT_ASK_USER").getBytes(StandardCharsets.UTF_8));
        assertThat(handler.askUser).isNotNull();
        assertThat(handler.askUser.payload().question()).isEqualTo("行程从哪天开始？");
        assertThat(handler.step).isNull();
        assertThat(handler.completed).isNull();
    }

    @Test
    void dispatchesAStepEventToTheHandler() {
        listener.consume(eventBody("AGENT_STEP").getBytes(StandardCharsets.UTF_8));
        assertThat(handler.step).isNotNull();
        assertThat(handler.step.payload().tool()).isEqualTo("ask_user");
    }

    @Test
    void dispatchesACompletedEventToTheHandler() {
        listener.consume(eventBody("AGENT_COMPLETED").getBytes(StandardCharsets.UTF_8));
        assertThat(handler.completed).isNotNull();
        assertThat(handler.completed.payload().summary()).isEqualTo("行程已生成：测试行程");
        // AUDIT-01（归边 A）：completed 事件不再携带 itinerary，仅摘要 + 槽位。
        assertThat(handler.completed.payload().slots().path("destination").path("value").asText())
                .isEqualTo("成都");
    }

    @Test
    void dispatchesARunFinishedEventToTheHandler() {
        listener.consume(eventBody("AGENT_RUN_FINISHED").getBytes(StandardCharsets.UTF_8));
        assertThat(handler.runFinished).isNotNull();
        assertThat(handler.runFinished.payload().status()).isEqualTo("STOPPED");
        assertThat(handler.runFinished.payload().reasonCode()).isEqualTo("CEILING_REACHED");
        assertThat(handler.askUser).isNull();
    }

    @Test
    void rejectsAnUnknownAgentEventTypeWithoutRequeue() {
        assertThatThrownBy(() -> listener.consume(
                eventBody("AGENT_PANIC").getBytes(StandardCharsets.UTF_8)
        ))
                .isInstanceOf(AmqpRejectAndDontRequeueException.class)
                .hasCauseInstanceOf(EventContractException.class);
    }

    @Test
    void rejectsInvalidJsonWithoutRequeue() {
        assertThatThrownBy(() -> listener.consume("not-json".getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(AmqpRejectAndDontRequeueException.class)
                .hasCauseInstanceOf(EventContractException.class);
    }

    private String eventBody(String eventType) {
        return AgentEventFixtures.load(switch (eventType) {
            case "AGENT_ASK_USER" -> "agent-ask-user-event-v1";
            case "AGENT_STEP" -> "agent-step-event-v1";
            case "AGENT_COMPLETED" -> "agent-completed-event-v1";
            case "AGENT_RUN_FINISHED" -> "agent-run-finished-event-v1";
            default -> "agent-ask-user-event-v1";
        }, "valid.json").replaceFirst(
                "\"eventType\": \"[A-Z_]+\"", "\"eventType\": \"" + eventType + "\""
        );
    }

    private static final class RecordingHandler implements AgentDialogEventHandler {

        private AgentAskUserEvent askUser;
        private AgentStepEvent step;
        private AgentCompletedEvent completed;
        private AgentRunFinishedEvent runFinished;

        @Override
        public void handleAskUser(AgentAskUserEvent event) {
            this.askUser = event;
        }

        @Override
        public void handleStep(AgentStepEvent event) {
            this.step = event;
        }

        @Override
        public void handleCompleted(AgentCompletedEvent event) {
            this.completed = event;
        }

        @Override
        public void handleRunFinished(AgentRunFinishedEvent event) {
            this.runFinished = event;
        }
    }
}
