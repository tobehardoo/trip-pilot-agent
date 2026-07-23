package io.github.tobehardoo.trippilot.messaging;

import io.github.tobehardoo.trippilot.planning.PlanningEventRejectedException;
import io.github.tobehardoo.trippilot.planning.PlanningFailureService;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
public class PlanningFailedEventListener {

    private final PlanningFailedEventParser parser;
    private final PlanningFailureService failureService;

    public PlanningFailedEventListener(PlanningFailedEventParser parser,
                                       PlanningFailureService failureService) {
        this.parser = parser;
        this.failureService = failureService;
    }

    @RabbitListener(
            queues = RabbitMessagingConfiguration.FAILED_QUEUE,
            autoStartup = "${app.messaging.event-consumer-enabled:true}"
    )
    public void consume(byte[] body) {
        try {
            failureService.handle(parser.parse(body));
        } catch (PlanningEventContractException | PlanningEventRejectedException exception) {
            throw new AmqpRejectAndDontRequeueException("Rejected PLANNING_FAILED event", exception);
        }
    }
}
