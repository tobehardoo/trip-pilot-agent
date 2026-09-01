package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.io.IOException;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.agentdialog.AgentDialogEventHandler;
import io.github.tobehardoo.trippilot.common.EventContractException;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
public class AgentDialogEventListener {

    private final ObjectMapper objectMapper;
    private final AgentAskUserEventParser askUserParser;
    private final AgentStepEventParser stepParser;
    private final AgentCompletedEventParser completedParser;
    private final AgentRunFinishedEventParser runFinishedParser;
    private final AgentDialogEventHandler eventHandler;

    public AgentDialogEventListener(
            ObjectMapper objectMapper,
            AgentAskUserEventParser askUserParser,
            AgentStepEventParser stepParser,
            AgentCompletedEventParser completedParser,
            AgentRunFinishedEventParser runFinishedParser,
            AgentDialogEventHandler eventHandler
    ) {
        this.objectMapper = objectMapper;
        this.askUserParser = askUserParser;
        this.stepParser = stepParser;
        this.completedParser = completedParser;
        this.runFinishedParser = runFinishedParser;
        this.eventHandler = eventHandler;
    }

    @RabbitListener(
            queues = RabbitMessagingConfiguration.AGENT_DIALOG_EVENT_QUEUE,
            autoStartup = "${app.messaging.event-consumer-enabled:true}"
    )
    public void consume(byte[] body) {
        try {
            String eventType = readEventType(body);
            switch (eventType) {
                case "AGENT_ASK_USER" -> eventHandler.handleAskUser(askUserParser.parse(body));
                case "AGENT_STEP" -> eventHandler.handleStep(stepParser.parse(body));
                case "AGENT_COMPLETED" ->
                        eventHandler.handleCompleted(completedParser.parse(body));
                case "AGENT_RUN_FINISHED" ->
                        eventHandler.handleRunFinished(runFinishedParser.parse(body));
                default -> throw new EventContractException(
                        "unsupported agent dialog event: " + eventType
                );
            }
        } catch (EventContractException exception) {
            throw new AmqpRejectAndDontRequeueException(
                    "Rejected agent dialog event", exception
            );
        }
    }

    private String readEventType(byte[] body) throws EventContractException {
        try {
            JsonNode tree = objectMapper.readTree(body);
            if (tree == null || !tree.isObject()) {
                throw new EventContractException("event body must contain a JSON object");
            }
            String eventType = tree.path("eventType").asText(null);
            if (eventType == null || eventType.isBlank()) {
                throw new EventContractException("eventType is required");
            }
            return eventType;
        } catch (IOException exception) {
            throw new EventContractException("event body is not valid JSON", exception);
        }
    }
}
