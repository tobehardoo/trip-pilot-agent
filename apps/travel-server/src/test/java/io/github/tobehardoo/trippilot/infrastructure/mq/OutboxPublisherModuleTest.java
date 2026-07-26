package io.github.tobehardoo.trippilot.infrastructure.mq;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThatCode;

class OutboxPublisherModuleTest {

    @Test
    void exposesAnOutboxPublicationService() {
        assertThatCode(() -> Class.forName(
                "io.github.tobehardoo.trippilot.infrastructure.mq.OutboxPublicationService"
        )).doesNotThrowAnyException();
    }

    @Test
    void exposesARabbitPlanningCommandPublisher() {
        assertThatCode(() -> Class.forName(
                "io.github.tobehardoo.trippilot.infrastructure.mq.RabbitPlanningCommandPublisher"
        )).doesNotThrowAnyException();
    }

    @Test
    void exposesRuntimeMessagingConfigurationAndScheduledJob() {
        assertThatCode(() -> Class.forName(
                "io.github.tobehardoo.trippilot.infrastructure.mq.RabbitMessagingConfiguration"
        )).doesNotThrowAnyException();
        assertThatCode(() -> Class.forName(
                "io.github.tobehardoo.trippilot.infrastructure.mq.OutboxPublisherJob"
        )).doesNotThrowAnyException();
    }
}
