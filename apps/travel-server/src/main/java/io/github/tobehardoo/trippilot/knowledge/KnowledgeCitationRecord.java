package io.github.tobehardoo.trippilot.knowledge;

import java.time.Instant;
import java.util.List;

/** 向量检索命中结果。 */
public record KnowledgeCitationRecord(
        String chunkId,
        String documentId,
        String title,
        String city,
        String category,
        String contentType,
        String regionCity,
        String regionDistrict,
        String sourceUrl,
        String sourceName,
        String reliabilityLevel,
        Instant collectedAt,
        String content,
        double similarity
) {
}