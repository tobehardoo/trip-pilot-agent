package io.github.tobehardoo.trippilot.messaging;

import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageBuilder;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

public class RabbitPlanningCommandPublisher implements PlanningCommandPublisher {

    private static final String COMMAND_EXCHANGE = "trip.command.exchange";
    private static final long CONFIRM_TIMEOUT_SECONDS = 5;

    private final RabbitTemplate rabbitTemplate;

    public RabbitPlanningCommandPublisher(RabbitTemplate rabbitTemplate) {
        this.rabbitTemplate = rabbitTemplate;
        this.rabbitTemplate.setMandatory(true);
    }

    @Override
    public void publish(OutboxEventRecord event) {
        Message message = MessageBuilder
                .withBody(event.payloadJson().getBytes(StandardCharsets.UTF_8))
                .setContentType("application/json")
                .setContentEncoding(StandardCharsets.UTF_8.name())
                .setDeliveryMode(MessageDeliveryMode.PERSISTENT)
                .setMessageId(event.id().toString())
                .setType(event.eventType())
                .build();
        CorrelationData correlation = new CorrelationData(event.id().toString());
        rabbitTemplate.send(COMMAND_EXCHANGE, event.routingKey(), message, correlation);

        try {
            CorrelationData.Confirm confirm = correlation.getFuture()
                    .get(CONFIRM_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            if (!confirm.isAck()) {
                throw new IllegalStateException(
                        "RabbitMQ rejected event " + event.id() + ": " + confirm.getReason()
                );
            }
            if (correlation.getReturned() != null) {
                throw new IllegalStateException("RabbitMQ returned unroutable event " + event.id());
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Interrupted while confirming event " + event.id(), exception);
        } catch (ExecutionException | TimeoutException exception) {
            throw new IllegalStateException("Could not confirm RabbitMQ event " + event.id(), exception);
        }
    }
}
