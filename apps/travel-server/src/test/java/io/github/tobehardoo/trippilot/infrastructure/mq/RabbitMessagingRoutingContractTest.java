package io.github.tobehardoo.trippilot.infrastructure.mq;

import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Queue;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Locks the Rabbit routing contract shared with the Python worker.
 */
class RabbitMessagingRoutingContractTest {

    @Test
    void reviewBindingUsesReviewRequiredRoutingKey() {
        RabbitMessagingConfiguration config = new RabbitMessagingConfiguration();
        Queue queue = config.planningReviewQueue();
        DirectExchange exchange = config.planningEventExchange();

        Binding binding = config.planningReviewBinding(queue, exchange);

        assertThat(binding.getRoutingKey()).isEqualTo("planning.review-required");
    }

    @Test
    void completedBindingUsesCompletedRoutingKey() {
        RabbitMessagingConfiguration config = new RabbitMessagingConfiguration();
        Queue queue = config.planningCompletedQueue();
        DirectExchange exchange = config.planningEventExchange();

        Binding binding = config.planningCompletedBinding(queue, exchange);

        assertThat(binding.getRoutingKey()).isEqualTo("planning.completed");
    }

    @Test
    void agentDialogEventQueueBindsAllAgentRoutingKeys() {
        RabbitMessagingConfiguration config = new RabbitMessagingConfiguration();
        Queue queue = config.agentDialogEventQueue();
        DirectExchange exchange = config.planningEventExchange();

        assertThat(config.agentDialogAskUserBinding(queue, exchange).getRoutingKey())
                .isEqualTo("agent.ask-user");
        assertThat(config.agentDialogStepBinding(queue, exchange).getRoutingKey())
                .isEqualTo("agent.step");
        assertThat(config.agentDialogCompletedBinding(queue, exchange).getRoutingKey())
                .isEqualTo("agent.completed");
        assertThat(config.agentDialogRunFinishedBinding(queue, exchange).getRoutingKey())
                .isEqualTo("agent.run-finished");
    }
}
