package io.github.tobehardoo.trippilot.messaging;

import java.time.Instant;
import java.util.UUID;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.rabbit.connection.CachingConnectionFactory;
import org.springframework.amqp.rabbit.core.RabbitAdmin;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.testcontainers.containers.RabbitMQContainer;

import static org.assertj.core.api.Assertions.assertThat;

class RabbitPlanningCommandPublisherIntegrationTest {

    private static final String EXCHANGE = "trip.command.exchange";
    private static final String ROUTING_KEY = "planning.create";
    private static final String QUEUE = "planning.create.publisher-test.queue";
    private static final RabbitMQContainer RABBIT = new RabbitMQContainer("rabbitmq:4.1-alpine");

    private static CachingConnectionFactory connectionFactory;
    private static RabbitTemplate rabbitTemplate;

    @BeforeAll
    static void startRabbit() {
        RABBIT.start();
        connectionFactory = new CachingConnectionFactory(RABBIT.getHost(), RABBIT.getAmqpPort());
        connectionFactory.setUsername(RABBIT.getAdminUsername());
        connectionFactory.setPassword(RABBIT.getAdminPassword());
        connectionFactory.setPublisherConfirmType(CachingConnectionFactory.ConfirmType.CORRELATED);
        connectionFactory.setPublisherReturns(true);
        rabbitTemplate = new RabbitTemplate(connectionFactory);
        rabbitTemplate.setMandatory(true);

        RabbitAdmin admin = new RabbitAdmin(connectionFactory);
        DirectExchange exchange = new DirectExchange(EXCHANGE, true, false);
        Queue queue = new Queue(QUEUE, false, false, true);
        admin.declareExchange(exchange);
        admin.declareQueue(queue);
        admin.declareBinding(BindingBuilder.bind(queue).to(exchange).with(ROUTING_KEY));
    }

    @AfterAll
    static void stopRabbit() {
        if (connectionFactory != null) {
            connectionFactory.destroy();
        }
        RABBIT.stop();
    }

    @Test
    void publishesPersistentJsonWithMessageIdentityAfterBrokerConfirmation() {
        UUID eventId = UUID.randomUUID();
        String payload = "{\"eventType\":\"PLANNING_CREATE_REQUESTED\"}";
        OutboxEventRecord event = new OutboxEventRecord(
                eventId, "PLANNING_TASK", UUID.randomUUID(),
                "PLANNING_CREATE_REQUESTED", ROUTING_KEY, payload, "PENDING",
                0, Instant.now(), null, Instant.now(), null
        );

        new RabbitPlanningCommandPublisher(rabbitTemplate).publish(event);

        Message message = rabbitTemplate.receive(QUEUE, 2_000);
        assertThat(message).isNotNull();
        assertThat(new String(message.getBody(), java.nio.charset.StandardCharsets.UTF_8)).isEqualTo(payload);
        assertThat(message.getMessageProperties().getContentType()).isEqualTo("application/json");
        assertThat(message.getMessageProperties().getReceivedDeliveryMode())
                .isEqualTo(MessageDeliveryMode.PERSISTENT);
        assertThat(message.getMessageProperties().getMessageId()).isEqualTo(eventId.toString());
        assertThat(message.getMessageProperties().getType()).isEqualTo("PLANNING_CREATE_REQUESTED");
    }
}
