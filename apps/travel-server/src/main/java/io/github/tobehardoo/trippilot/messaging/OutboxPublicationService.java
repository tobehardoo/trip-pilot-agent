package io.github.tobehardoo.trippilot.messaging;

public class OutboxPublicationService {

    private static final int BATCH_SIZE = 50;

    private final OutboxPublicationAttempt publicationAttempt;

    public OutboxPublicationService(OutboxPublicationAttempt publicationAttempt) {
        this.publicationAttempt = publicationAttempt;
    }

    public int publishBatch() {
        int processed = 0;
        while (processed < BATCH_SIZE && publicationAttempt.publishNext()) {
            processed++;
        }
        return processed;
    }
}
