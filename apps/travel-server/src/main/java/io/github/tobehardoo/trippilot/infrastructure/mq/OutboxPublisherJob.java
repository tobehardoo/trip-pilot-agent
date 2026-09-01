package io.github.tobehardoo.trippilot.infrastructure.mq;

import org.springframework.scheduling.annotation.Scheduled;

public class OutboxPublisherJob {

    private final OutboxPublicationService publicationService;

    public OutboxPublisherJob(OutboxPublicationService publicationService) {
        this.publicationService = publicationService;
    }

    @Scheduled(fixedDelayString = "${app.messaging.outbox-publisher-delay-ms:1000}")
    public void publishPending() {
        publicationService.publishBatch();
    }
}
