package io.github.tobehardoo.trippilot.messaging;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThatCode;

class OutboxPublisherModuleTest {

    @Test
    void exposesAnOutboxPublicationService() {
        assertThatCode(() -> Class.forName(
                "io.github.tobehardoo.trippilot.messaging.OutboxPublicationService"
        )).doesNotThrowAnyException();
    }

    @Test
    void exposesARabbitPlanningCommandPublisher() {
        assertThatCode(() -> Class.forName(
                "io.github.tobehardoo.trippilot.messaging.RabbitPlanningCommandPublisher"
        )).doesNotThrowAnyException();
    }

    @Test
    void exposesRuntimeMessagingConfigurationAndScheduledJob() {
        assertThatCode(() -> Class.forName(
                "io.github.tobehardoo.trippilot.messaging.RabbitMessagingConfiguration"
        )).doesNotThrowAnyException();
        assertThatCode(() -> Class.forName(
                "io.github.tobehardoo.trippilot.messaging.OutboxPublisherJob"
        )).doesNotThrowAnyException();
    }
}
