package io.github.tobehardoo.trippilot.knowledge;

/** 知识库文档的最新版本行（列表 / 详情元数据）。 seasons/types 以逗号分隔字符串透出。 */
public record KnowledgeRecord(
        String documentId,
        String title,
        String city,
        String category,
        int version,
        String sourceUrl,
        String sourceName,
        String reliabilityLevel,
        java.time.Instant collectedAt,
        java.time.LocalDate validFrom,
        java.time.LocalDate validTo,
        String applicableSeasons,
        String travelerTypes,
        String content,
        int chunkCount,
        String contentHash,
        String contentType,
        String regionProvince,
        String regionCity,
        String regionDistrict
) {
}