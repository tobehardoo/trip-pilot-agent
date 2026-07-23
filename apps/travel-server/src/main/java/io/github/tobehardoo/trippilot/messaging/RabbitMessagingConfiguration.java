package io.github.tobehardoo.trippilot.messaging;

import java.time.Clock;

import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.amqp.core.TopicExchange;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class RabbitMessagingConfiguration {

    static final String COMMAND_EXCHANGE = "trip.command.exchange";
    static final String EVENT_EXCHANGE = "trip.event.exchange";
    static final String DEAD_LETTER_EXCHANGE = "trip.dead-letter.exchange";
    static final String CREATE_QUEUE = "planning.create.queue";
    static final String CANCEL_QUEUE = "planning.cancel.queue";
    static final String PROGRESS_QUEUE = "planning.progress.queue";
    static final String COMPLETED_QUEUE = "planning.completed.queue";
    static final String FAILED_QUEUE = "planning.failed.queue";
    static final String DEAD_LETTER_QUEUE = "planning.dead-letter.queue";

    @Bean
    DirectExchange planningCommandExchange() {
        return new DirectExchange(COMMAND_EXCHANGE, true, false);
    }

    @Bean
    DirectExchange planningEventExchange() {
        return new DirectExchange(EVENT_EXCHANGE, true, false);
    }

    @Bean
    TopicExchange planningDeadLetterExchange() {
        return new TopicExchange(DEAD_LETTER_EXCHANGE, true, false);
    }

    @Bean
    Queue planningCreateQueue() {
        return durableQueue(CREATE_QUEUE, "planning.create.dead");
    }

    @Bean
    Queue planningCancelQueue() {
        return durableQueue(CANCEL_QUEUE, "planning.cancel.dead");
    }

    @Bean
    Queue planningProgressQueue() {
        return durableQueue(PROGRESS_QUEUE, "planning.progress.dead");
    }

    @Bean
    Queue planningCompletedQueue() {
        return durableQueue(COMPLETED_QUEUE, "planning.completed.dead");
    }

    @Bean
    Queue planningFailedQueue() {
        return durableQueue(FAILED_QUEUE, "planning.failed.dead");
    }

    @Bean
    Queue planningDeadLetterQueue() {
        return QueueBuilder.durable(DEAD_LETTER_QUEUE).build();
    }

    @Bean
    Binding planningCreateBinding(Queue planningCreateQueue, DirectExchange planningCommandExchange) {
        return BindingBuilder.bind(planningCreateQueue).to(planningCommandExchange).with("planning.create");
    }

    @Bean
    Binding planningCancelBinding(Queue planningCancelQueue, DirectExchange planningCommandExchange) {
        return BindingBuilder.bind(planningCancelQueue).to(planningCommandExchange).with("planning.cancel");
    }

    @Bean
    Binding planningProgressBinding(Queue planningProgressQueue, DirectExchange planningEventExchange) {
        return BindingBuilder.bind(planningProgressQueue).to(planningEventExchange).with("planning.progress");
    }

    @Bean
    Binding planningCompletedBinding(Queue planningCompletedQueue, DirectExchange planningEventExchange) {
        return BindingBuilder.bind(planningCompletedQueue).to(planningEventExchange).with("planning.completed");
    }

    @Bean
    Binding planningFailedBinding(Queue planningFailedQueue, DirectExchange planningEventExchange) {
        return BindingBuilder.bind(planningFailedQueue).to(planningEventExchange).with("planning.failed");
    }

    @Bean
    Binding planningDeadLetterBinding(Queue planningDeadLetterQueue,
                                      TopicExchange planningDeadLetterExchange) {
        return BindingBuilder.bind(planningDeadLetterQueue)
                .to(planningDeadLetterExchange)
                .with("planning.#");
    }

    @Bean
    PlanningCommandPublisher planningCommandPublisher(RabbitTemplate rabbitTemplate) {
        return new RabbitPlanningCommandPublisher(rabbitTemplate);
    }

    @Bean
    Clock systemClock() {
        return Clock.systemUTC();
    }

    @Bean
    OutboxPublicationAttempt outboxPublicationAttempt(OutboxMapper outboxMapper,
                                                       PlanningCommandPublisher commandPublisher,
                                                       Clock systemClock) {
        return new TransactionalOutboxPublicationAttempt(outboxMapper, commandPublisher, systemClock);
    }

    @Bean
    OutboxPublicationService outboxPublicationService(OutboxPublicationAttempt publicationAttempt) {
        return new OutboxPublicationService(publicationAttempt);
    }

    @Bean
    @ConditionalOnProperty(
            name = "app.messaging.outbox-publisher-enabled",
            havingValue = "true",
            matchIfMissing = true
    )
    OutboxPublisherJob outboxPublisherJob(OutboxPublicationService publicationService) {
        return new OutboxPublisherJob(publicationService);
    }

    private Queue durableQueue(String name, String deadLetterRoutingKey) {
        return QueueBuilder.durable(name)
                .deadLetterExchange(DEAD_LETTER_EXCHANGE)
                .deadLetterRoutingKey(deadLetterRoutingKey)
                .build();
    }
}
