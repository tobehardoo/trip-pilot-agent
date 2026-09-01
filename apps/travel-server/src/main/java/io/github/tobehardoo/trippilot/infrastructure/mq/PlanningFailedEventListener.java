package io.github.tobehardoo.trippilot.infrastructure.mq;

import io.github.tobehardoo.trippilot.common.EventContractException;
import io.github.tobehardoo.trippilot.common.EventRejectedException;
import io.github.tobehardoo.trippilot.planning.PlanningFailureService;
import io.github.tobehardoo.trippilot.planning.PlanningLogContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
public class PlanningFailedEventListener {

    private static final Logger log = LoggerFactory.getLogger(PlanningFailedEventListener.class);

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
        try (PlanningLogContext ctx = PlanningLogContext.open()) {
            PlanningFailedEvent event = parser.parse(body);
            ctx.put(PlanningLogContext.EVENT_ID, str(event.eventId()))
                    .put(PlanningLogContext.TRACE_ID, str(event.traceId()))
                    .put(PlanningLogContext.TASK_ID, str(event.taskId()))
                    .put(PlanningLogContext.TRIP_ID, str(event.tripId()))
                    .put(PlanningLogContext.RUN_ID, str(event.runId()))
                    .put(PlanningLogContext.EVENT_TYPE, event.eventType())
                    .put(PlanningLogContext.SCHEMA_VERSION, String.valueOf(event.schemaVersion()))
                    .put(PlanningLogContext.OUTCOME_STATUS, event.payload() == null
                            ? null : event.payload().status());
            log.info("message received: PLANNING_FAILED");
            failureService.handle(event);
        } catch (EventContractException | EventRejectedException exception) {
            log.warn("contract rejected: PLANNING_FAILED event ({})",
                    exception.getClass().getSimpleName());
            throw new AmqpRejectAndDontRequeueException("Rejected PLANNING_FAILED event", exception);
        }
    }

    private static String str(java.util.UUID value) {
        return value == null ? null : value.toString();
    }
}
