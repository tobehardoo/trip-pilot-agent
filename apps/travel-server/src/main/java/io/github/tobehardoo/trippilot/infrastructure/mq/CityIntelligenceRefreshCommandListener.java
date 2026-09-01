package io.github.tobehardoo.trippilot.infrastructure.mq;

import io.github.tobehardoo.trippilot.cityintelligence.CityIntelligenceRefreshProcessor;
import io.github.tobehardoo.trippilot.common.EventContractException;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
public class CityIntelligenceRefreshCommandListener {

    private final CityIntelligenceRefreshCommandParser parser;
    private final CityIntelligenceRefreshProcessor processor;

    public CityIntelligenceRefreshCommandListener(
            CityIntelligenceRefreshCommandParser parser,
            CityIntelligenceRefreshProcessor processor
    ) {
        this.parser = parser;
        this.processor = processor;
    }

    @RabbitListener(
            queues = RabbitMessagingConfiguration.CITY_REFRESH_QUEUE,
            autoStartup = "${app.messaging.event-consumer-enabled:true}"
    )
    public void consume(byte[] body) {
        try {
            processor.process(parser.parse(body).refreshId());
        } catch (EventContractException exception) {
            throw new AmqpRejectAndDontRequeueException(
                    "Rejected CITY_INTELLIGENCE_REFRESH_REQUESTED command",
                    exception
            );
        }
    }
}
