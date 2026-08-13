package io.github.tobehardoo.trippilot.infrastructure.mq;

import io.github.tobehardoo.trippilot.planning.PlanningEventRejectedException;
import io.github.tobehardoo.trippilot.planning.PlanningLogContext;
import io.github.tobehardoo.trippilot.planning.PlanningReviewHandler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
public class PlanningReviewRequiredEventListener {

    private static final Logger log = LoggerFactory.getLogger(PlanningReviewRequiredEventListener.class);

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
        try (PlanningLogContext ctx = PlanningLogContext.open()) {
            PlanningReviewRequiredEvent event = parser.parse(body);
            ctx.put(PlanningLogContext.EVENT_ID, str(event.eventId()))
                    .put(PlanningLogContext.TRACE_ID, str(event.traceId()))
                    .put(PlanningLogContext.TASK_ID, str(event.taskId()))
                    .put(PlanningLogContext.TRIP_ID, str(event.tripId()))
                    .put(PlanningLogContext.RUN_ID, str(event.runId()))
                    .put(PlanningLogContext.EVENT_TYPE, event.eventType())
                    .put(PlanningLogContext.SCHEMA_VERSION, String.valueOf(event.schemaVersion()));
            log.info("message received: PLANNING_REVIEW_REQUIRED");
            reviewHandler.handle(event);
        } catch (PlanningEventContractException | PlanningEventRejectedException exception) {
            log.warn("contract rejected: PLANNING_REVIEW_REQUIRED event ({})",
                    exception.getClass().getSimpleName());
            throw new AmqpRejectAndDontRequeueException(
                    "Rejected PLANNING_REVIEW_REQUIRED event", exception
            );
        }
    }

    private static String str(java.util.UUID value) {
        return value == null ? null : value.toString();
    }
}
