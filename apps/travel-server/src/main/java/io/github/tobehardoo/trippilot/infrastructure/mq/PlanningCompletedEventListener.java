package io.github.tobehardoo.trippilot.infrastructure.mq;

import io.github.tobehardoo.trippilot.planning.PlanningCompletionHandler;
import io.github.tobehardoo.trippilot.planning.PlanningEventRejectedException;
import io.github.tobehardoo.trippilot.planning.PlanningLogContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
public class PlanningCompletedEventListener {

    private static final Logger log = LoggerFactory.getLogger(PlanningCompletedEventListener.class);

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
        try (PlanningLogContext ctx = PlanningLogContext.open()) {
            PlanningCompletedEvent event = parser.parse(body);
            ctx.put(PlanningLogContext.EVENT_ID, str(event.eventId()))
                    .put(PlanningLogContext.TRACE_ID, str(event.traceId()))
                    .put(PlanningLogContext.TASK_ID, str(event.taskId()))
                    .put(PlanningLogContext.TRIP_ID, str(event.tripId()))
                    .put(PlanningLogContext.RUN_ID, str(event.runId()))
                    .put(PlanningLogContext.EVENT_TYPE, event.eventType())
                    .put(PlanningLogContext.SCHEMA_VERSION, String.valueOf(event.schemaVersion()));
            log.info("message received: PLANNING_COMPLETED schemaVersion={}", event.schemaVersion());
            completionHandler.handle(event);
        } catch (PlanningEventContractException | PlanningEventRejectedException exception) {
            log.warn("contract rejected: PLANNING_COMPLETED event ({})",
                    exception.getClass().getSimpleName());
            throw new AmqpRejectAndDontRequeueException(
                    "Rejected PLANNING_COMPLETED event", exception
            );
        }
    }

    private static String str(java.util.UUID value) {
        return value == null ? null : value.toString();
    }
}
