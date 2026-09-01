package io.github.tobehardoo.trippilot.infrastructure.mq;

import io.github.tobehardoo.trippilot.common.EventContractException;
import io.github.tobehardoo.trippilot.common.EventRejectedException;
import io.github.tobehardoo.trippilot.planning.PlanningProgressHandler;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
public class PlanningProgressEventListener {

    private final PlanningProgressEventParser parser;
    private final PlanningProgressHandler progressHandler;

    public PlanningProgressEventListener(PlanningProgressEventParser parser,
                                         PlanningProgressHandler progressHandler) {
        this.parser = parser;
        this.progressHandler = progressHandler;
    }

    @RabbitListener(
            queues = RabbitMessagingConfiguration.PROGRESS_QUEUE,
            autoStartup = "${app.messaging.event-consumer-enabled:true}"
    )
    public void consume(byte[] body) {
        try {
            progressHandler.handle(parser.parse(body));
        } catch (EventContractException | EventRejectedException exception) {
            throw new AmqpRejectAndDontRequeueException(
                    "Rejected PLANNING_PROGRESS event", exception
            );
        }
    }
}
