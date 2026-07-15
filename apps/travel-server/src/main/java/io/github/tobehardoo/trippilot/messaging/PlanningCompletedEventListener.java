package io.github.tobehardoo.trippilot.messaging;

import io.github.tobehardoo.trippilot.planning.PlanningCompletionHandler;
import io.github.tobehardoo.trippilot.planning.PlanningEventRejectedException;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
public class PlanningCompletedEventListener {

    private final PlanningCompletedEventParser parser;
    private final PlanningCompletionHandler completionHandler;

    public PlanningCompletedEventListener(PlanningCompletedEventParser parser,
                                          PlanningCompletionHandler completionHandler) {
        this.parser = parser;
        this.completionHandler = completionHandler;
    }

    @RabbitListener(
            queues = RabbitMessagingConfiguration.COMPLETED_QUEUE,
            autoStartup = "${app.messaging.event-consumer-enabled:true}"
    )
    public void consume(byte[] body) {
        try {
            completionHandler.handle(parser.parse(body));
        } catch (PlanningEventContractException | PlanningEventRejectedException exception) {
            throw new AmqpRejectAndDontRequeueException(
                    "Rejected PLANNING_COMPLETED event", exception
            );
        }
    }
}
