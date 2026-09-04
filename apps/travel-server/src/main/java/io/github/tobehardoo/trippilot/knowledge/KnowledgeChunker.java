package io.github.tobehardoo.trippilot.knowledge;

import java.util.ArrayList;
import java.util.List;

/**
 * 把一篇攻略正文切成可独立检索的文本块（借鉴 Spring AI TokenTextSplitter 思路：
 * 按段落/标点分块，丢弃整篇一个向量的做法）。每块再单独嵌入、入库并携带元数据，
 * 检索时可在块粒度做相似度 + 文档级去重。
 */
public final class KnowledgeChunker {

    /** 每块目标字符上限（中文按字符计）。 */
    static final int MAX_CHUNK_CHARS = 500;
    /** 相邻块重叠字符数，缓解被切在句子中间丢语义。 */
    static final int OVERLAP_CHARS = 40;

    private KnowledgeChunker() {
    }

    /**
     * 按空行分段后贪婪打包为若干 chunk。
     *
     * @return 至少一个 chunk（空/短输入也返回一个单块）
     */
    public static List<Chunk> chunk(String content) {
        List<String> paragraphs = splitParagraphs(content);
        List<Chunk> chunks = new ArrayList<>();
        StringBuilder buffer = new StringBuilder();
        int index = 0;

        for (String paragraph : paragraphs) {
            if (paragraph.isEmpty()) {
                continue;
            }
            int room = MAX_CHUNK_CHARS - buffer.length();
            if (buffer.length() > 0 && paragraph.length() > room) {
                chunks.add(new Chunk(index++, buffer.toString().trim()));
                buffer.setLength(0);
                // 尾部 overlap：取上一段收尾若干字符，承接被切断的语义
                if (!chunks.isEmpty()) {
                    String prev = chunks.get(chunks.size() - 1).text();
                    if (prev.length() >= OVERLAP_CHARS) {
                        buffer.append(prev, prev.length() - OVERLAP_CHARS, prev.length()).append('\n');
                    }
                }
            }
            if (buffer.length() > 0) {
                buffer.append('\n');
            }
            buffer.append(paragraph);
        }
        if (buffer.length() > 0) {
            chunks.add(new Chunk(index, buffer.toString().trim()));
        }
        if (chunks.isEmpty()) {
            chunks.add(new Chunk(0, ""));
        }
        return chunks;
    }

    private static List<String> splitParagraphs(String content) {
        String normalized = (content == null ? "" : content).replace("\r\n", "\n").replace('\r', '\n');
        String[] parts = normalized.split("\n\\s*\n");
        List<String> paragraphs = new ArrayList<>(parts.length);
        for (String part : parts) {
            String compact = compact(part);
            if (!compact.isEmpty()) {
                paragraphs.add(compact);
            }
        }
        return paragraphs;
    }

    private static String compact(String text) {
        String[] lines = text.split("\n");
        List<String> kept = new ArrayList<>(lines.length);
        for (String line : lines) {
            String s = line.trim();
            if (!s.isEmpty()) {
                kept.add(s);
            }
        }
        return String.join("\n", kept);
    }

    /** 一个文本块：全局内序号 + 压缩后的原文。 */
    public record Chunk(int index, String text) {
    }
}