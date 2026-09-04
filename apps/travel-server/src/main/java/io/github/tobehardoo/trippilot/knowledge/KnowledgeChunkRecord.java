package io.github.tobehardoo.trippilot.knowledge;

/** 知识库文档的单个分块；headingPath 以逗号分隔字符串透出。 */
public record KnowledgeChunkRecord(
        String chunkId,
        int chunkIndex,
        String headingPath,
        String contentType,
        String content
) {
}