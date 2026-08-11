package io.github.tobehardoo.trippilot.infrastructure.mq;

import io.github.tobehardoo.trippilot.planning.PlanningEventRejectedException;
import io.github.tobehardoo.trippilot.planning.PlanningReviewHandler;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
public class PlanningReviewRequiredEventListener {

    private final PlanningReviewRequiredEventParser parser;
    private final PlanningReviewHandler reviewHandler;

    public PlanningReviewRequiredEventListener(PlanningReviewRequiredEventParser parser,
                                               PlanningReviewHandler reviewHandler) {
        this.parser = parser;
        this.reviewHandler = reviewHandler;
    }

    @RabbitListener(
            queues = RabbitMessagingConfiguration.REVIEW_QUEUE,
            autoStartup = "${app.messaging.event-consumer-enabled:true}"
    )
    public void consume(byte[] body) {
        try {
            reviewHandler.handle(parser.parse(body));
        } catch (PlanningEventContractException | PlanningEventRejectedException exception) {
            throw new AmqpRejectAndDontRequeueException(
                    "Rejected PLANNING_REVIEW_REQUIRED event", exception
            );
        }
    }
}
