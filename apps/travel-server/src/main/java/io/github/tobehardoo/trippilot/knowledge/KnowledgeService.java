package io.github.tobehardoo.trippilot.knowledge;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import io.github.tobehardoo.trippilot.guide.GuideImagePayload;
import io.github.tobehardoo.trippilot.guide.GuideImportRequest;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient;
import io.github.tobehardoo.trippilot.guide.GuideIntelligenceClient.FetchedGuide;

/** 知识库管理用例：列表 / 详情 / 删除 / 检索 / 导入（含 demo 嵌入）。 */
@Service
public class KnowledgeService {

    private static final Set<String> CATEGORIES = Set.of(
            "accommodation", "culture", "food", "poi", "season", "theme", "travel_tip");
    private static final Set<String> RELIABILITY = Set.of("OFFICIAL", "CURATED", "COMMUNITY");
    /** 需经 agent 管线先抓取/识别正文的导入渠道。 */
    private static final Set<String> EXTRACT_CHANNELS =
            Set.of("IMAGE_OCR", "DOUYIN_VIDEO", "XIAOHONGSHU_VIDEO");

    private final KnowledgeMapper mapper;
    private final GuideIntelligenceClient guideClient;
    private final KnowledgeEmbeddingClient embeddingClient;

    public KnowledgeService(
            KnowledgeMapper mapper,
            GuideIntelligenceClient guideClient,
            KnowledgeEmbeddingClient embeddingClient
    ) {
        this.mapper = mapper;
        this.guideClient = guideClient;
        this.embeddingClient = embeddingClient;
    }

    @Transactional(readOnly = true)
    public KnowledgePage list(String city, String keyword, int page, int size) {
        int offset = Math.max(page - 1, 0) * Math.max(size, 1);
        int limit = Math.min(Math.max(size, 1), 200);
        String c = blankToNull(city);
        String k = blankToNull(keyword);
        List<KnowledgeRecord> items = mapper.list(c, k, offset, limit);
        return new KnowledgePage(items, (int) mapper.count(c, k), Math.max(page, 1), Math.max(size, 1));
    }

    @Transactional(readOnly = true)
    public KnowledgeDetail detail(String documentId) {
        KnowledgeRecord doc = mapper.findLatest(documentId)
                .orElseThrow(() -> new NotFound(documentId));
        return new KnowledgeDetail(doc, mapper.chunks(documentId, doc.version()));
    }

    @Transactional
    public void delete(String documentId) {
        // chunk 行先删（embedding 级联），最后删文档（ON DELETE RESTRICT）。
        mapper.deleteChunks(documentId);
        mapper.deleteDocument(documentId);
    }

    @Transactional(readOnly = true)
    public List<KnowledgeCitationRecord> search(
            String query, String city,
            String regionProvince, String regionCity, String regionDistrict,
            String category, String contentType, String reliability,
            int limit, double minSimilarity, int topKPerDocument
    ) {
        if (query == null || query.isBlank()) {
            return List.of();
        }
        // 查询向量与写入用同一 provider/model 嵌入，保证可比对。
        KnowledgeEmbeddingClient.EmbeddingBatch batch = embeddingClient.embed(List.of(query));
        String embedding = DemoEmbedding.toVectorLiteral(batch.vectors().get(0));
        int perDoc = topKPerDocument <= 0 ? 3 : Math.min(topKPerDocument, 10);
        // 默认阈值下限：相似度为 0（完全无关）的命中不显示。
        double effectiveMin = minSimilarity <= 0 ? MIN_SIMILARITY : minSimilarity;
        return mapper.search(
                embedding, batch.model(), batch.dimensions(),
                blankToNull(city),
                blankToNull(regionProvince), blankToNull(regionCity), blankToNull(regionDistrict),
                blankToNull(category), blankToNull(contentType), blankToNull(reliability),
                effectiveMin, perDoc, Math.min(Math.max(limit, 1), 50));
    }

    /** 相似度下限：过滤掉相似度为 0 的无关联块，同时不对哈希向量的弱语义结果误杀。 */
    static final double MIN_SIMILARITY = 0.0001;

    /** 批量删除（软/物理删除文档、分块与向量）。幂等。 */
    @Transactional
    public void deleteMany(List<String> documentIds) {
        for (String id : documentIds) {
            if (id == null || id.isBlank()) {
                continue;
            }
            mapper.deleteChunks(id);
            mapper.deleteDocument(id);
        }
    }

    /**
     * 编辑已有文档。仅更新元数据；若提供了不同正文则重分块、重嵌入并 bump 版本。
     * city/title 不可变（改它们请删除后重新导入）。
     */
    @Transactional
    public KnowledgeRecord edit(String documentId, EditInput input) {
        KnowledgeRecord latest = mapper.findLatest(documentId)
                .orElseThrow(() -> new NotFound(documentId));
        String city = latest.city();
        String category = pick(input.category(), latest.category());
        if (!CATEGORIES.contains(category)) {
            throw new IllegalArgumentException("unsupported knowledge category: " + category);
        }
        String reliability = pick(input.reliabilityLevel(), latest.reliabilityLevel());
        if (!RELIABILITY.contains(reliability)) {
            throw new IllegalArgumentException("unsupported reliability level: " + reliability);
        }
        String sourceName = pick(input.sourceName(), latest.sourceName());
        LocalDate validFrom = input.validFrom() != null ? input.validFrom() : latest.validFrom();
        LocalDate validTo = input.validTo() != null ? input.validTo() : latest.validTo();

        boolean contentChanged = input.content() != null && !input.content().isBlank()
                && !input.content().trim().equals(latest.content());
        String newContent = contentChanged ? input.content().trim() : latest.content();

        // 地区：输入覆盖优先，缺省从城市/正文推导；板块：输入覆盖优先，否则重新归类。
        String regionCity = pick(input.regionCity(), latest.regionCity() != null ? latest.regionCity() : city);
        KnowledgeClassifier.ResolvedRegion region = KnowledgeClassifier.resolveRegion(
                pick(input.regionProvince(), latest.regionProvince()),
                regionCity,
                pick(input.regionDistrict(), latest.regionDistrict()),
                newContent);
        String docType;
        if (input.contentType() != null && !input.contentType().isBlank()) {
            docType = input.contentType().trim();
        } else if (contentChanged) {
            docType = KnowledgeClassifier.classify(newContent);
        } else if (latest.contentType() != null && !latest.contentType().isBlank()) {
            docType = latest.contentType();
        } else {
            docType = KnowledgeClassifier.classify(newContent);
        }

        int version;
        if (!contentChanged) {
            version = latest.version();
            mapper.updateDocumentMetadata(documentId, version, category, docType,
                    region.province(), region.city(), region.district(),
                    sourceName, reliability, validFrom, validTo);
        } else {
            Integer maxVersion = mapper.maxVersion(documentId);
            version = maxVersion == null ? 1 : maxVersion + 1;
            String contentHash = DemoEmbedding.sha256Hex(newContent);
            KnowledgeRecord doc = new KnowledgeRecord(
                    documentId, latest.title(), city, category, version, latest.sourceUrl(), sourceName,
                    reliability, Instant.now(), validFrom, validTo,
                    "{}", "{}", newContent, 0, contentHash,
                    docType, region.province(), region.city(), region.district());
            List<KnowledgeChunker.Chunk> chunks = KnowledgeChunker.chunk(newContent);
            List<String> chunkTexts = chunks.stream().map(KnowledgeChunker.Chunk::text)
                    .collect(java.util.stream.Collectors.toList());
            KnowledgeEmbeddingClient.EmbeddingBatch embedding = embeddingClient.embed(chunkTexts);
            doc = new KnowledgeRecord(documentId, latest.title(), city, category, version,
                    latest.sourceUrl(), sourceName, reliability, Instant.now(), validFrom, validTo,
                    "{}", "{}", newContent, chunks.size(), contentHash,
                    docType, region.province(), region.city(), region.district());
            mapper.insertDocument(doc);
            for (int i = 0; i < chunks.size(); i++) {
                KnowledgeChunker.Chunk chunk = chunks.get(i);
                String chunkId = UUID.randomUUID().toString();
                String chunkType = KnowledgeClassifier.classifyType(chunk.text(), input.contentType());
                mapper.insertChunk(chunkId, documentId, version, i, "{}", chunkType,
                        chunk.text(), DemoEmbedding.sha256Hex(chunk.text()),
                        DemoEmbedding.tokenCount(chunk.text()));
                mapper.insertEmbedding(chunkId, embedding.model(), embedding.dimensions(),
                        DemoEmbedding.toVectorLiteral(embedding.vectors().get(i)));
            }
        }
        return mapper.findLatest(documentId).orElseThrow(() -> new NotFound(documentId));
    }

    private static String pick(String value, String fallback) {
        if (value != null && !value.isBlank()) {
            return value.trim();
        }
        return fallback;
    }

    /**
     * 导入一篇攻略为知识库文档（单分块，demo 嵌入）。
     * <p>渠道由 {@code sourceType} 决定：PASTE_TEXT 直接用正文；IMAGE_OCR 把截图
     * 交给 agent 管线识别正文；DOUYIN_VIDEO / XIAOHONGSHU_VIDEO 抓取视频/笔记页正文。
     */
    @Transactional
    public ImportResult importDocument(ImportInput input) {
        String city = require(input.city(), "city");
        String category = input.category();
        if (!CATEGORIES.contains(category)) {
            throw new IllegalArgumentException("unsupported knowledge category: " + category);
        }
        String reliability = input.reliabilityLevel() == null || input.reliabilityLevel().isBlank()
                ? "COMMUNITY" : input.reliabilityLevel();
        if (!RELIABILITY.contains(reliability)) {
            throw new IllegalArgumentException("unsupported reliability level: " + reliability);
        }

        ResolvedSource resolved = resolveSource(input);
        String content = resolved.content().trim();
        if (content.isBlank()) {
            throw new IllegalArgumentException(resolved.reason() == null
                    ? "正文不能为空，请粘贴攻略正文后重试。" : resolved.reason());
        }
        String title = hasText(resolved.title()) ? resolved.title().trim() : city + " 攻略";
        String sourceName = hasText(resolved.sourceName()) ? resolved.sourceName().trim() : title;
        String sourceUrl = hasText(resolved.sourceUrl())
                ? resolved.sourceUrl().trim() : defaultSourceUrl(city, title);

        String documentId = slugId(city, title);
        String contentHash = DemoEmbedding.sha256Hex(content);

        Integer maxVersion = mapper.maxVersion(documentId);
        int version;
        if (maxVersion != null && contentHash.equals(mapper.contentHash(documentId, maxVersion).orElse(null))) {
            return new ImportResult(documentId, maxVersion, "UNCHANGED");
        }
        version = maxVersion == null ? 1 : maxVersion + 1;

        // 分块 → 批量真嵌入 → 逐 chunk 落库（含 embedding），整段在一个事务里。
        List<KnowledgeChunker.Chunk> chunks = KnowledgeChunker.chunk(content);
        List<String> chunkTexts = chunks.stream()
                .map(KnowledgeChunker.Chunk::text)
                .collect(java.util.stream.Collectors.toList());
        KnowledgeEmbeddingClient.EmbeddingBatch embedding = embeddingClient.embed(chunkTexts);

        // 两轴元数据：地区(省/市/区，自动推导) + 板块(文档级可覆盖，块级自动归类)
        String regionCity = hasText(input.regionCity()) ? input.regionCity().trim() : city;
        KnowledgeClassifier.ResolvedRegion region = KnowledgeClassifier.resolveRegion(
                input.regionProvince(), regionCity, input.regionDistrict(), content);
        String docType = input.contentType() == null || input.contentType().isBlank()
                ? KnowledgeClassifier.classify(content) : input.contentType().trim();

        KnowledgeRecord doc = new KnowledgeRecord(
                documentId, title, city, category, version, sourceUrl, sourceName,
                reliability, Instant.now(), input.validFrom(), input.validTo(),
                "{}", "{}", content, chunks.size(), contentHash,
                docType, region.province(), region.city(), region.district());
        mapper.insertDocument(doc);

        for (int i = 0; i < chunks.size(); i++) {
            KnowledgeChunker.Chunk chunk = chunks.get(i);
            String chunkId = UUID.randomUUID().toString();
            String chunkType = KnowledgeClassifier.classifyType(chunk.text(), input.contentType());
            mapper.insertChunk(chunkId, documentId, version, i, "{}", chunkType,
                    chunk.text(), DemoEmbedding.sha256Hex(chunk.text()),
                    DemoEmbedding.tokenCount(chunk.text()));
            mapper.insertEmbedding(chunkId, embedding.model(), embedding.dimensions(),
                    DemoEmbedding.toVectorLiteral(embedding.vectors().get(i)));
        }
        return new ImportResult(documentId, version, "CREATED");
    }

    /** 按渠道解析正文、标题、来源；正文不可得时给出可读原因。 */
    private ResolvedSource resolveSource(ImportInput input) {
        String type = input.sourceType() == null || input.sourceType().isBlank()
                ? "" : input.sourceType().trim();
        if ("IMAGE_OCR".equals(type)) {
            return resolveImages(input);
        }
        if ("XIAOHONGSHU_VIDEO".equals(type)) {
            return resolveVideoLink(input, "小红书");
        }
        if ("DOUYIN_VIDEO".equals(type)) {
            return resolveVideoLink(input, "抖音");
        }
        if (EXTRACT_CHANNELS.contains(type)) {
            throw new IllegalArgumentException("unsupported import source type: " + type);
        }
        boolean hasContent = hasText(input.content());
        boolean hasUrl = hasText(input.sourceUrl());
        // 没有粘贴正文但带有链接 → 交给通用平台链接解析（抖音/小红书/微博/B站/知乎等）
        if (!hasContent && hasUrl) {
            return resolveVideoLink(input, "链接");
        }
        return new ResolvedSource(
                require(input.content(), "content"),
                require(input.title(), "title"),
                input.sourceName(),
                input.sourceUrl(),
                null);
    }

    private ResolvedSource resolveImages(ImportInput input) {
        if (input.images() == null || input.images().isEmpty()) {
            throw new IllegalArgumentException("图片识别导入需要至少一张攻略截图。");
        }
        FetchedGuide fetched = guideClient.fetch(new GuideImportRequest(
                null, "IMAGE_OCR", null, null, null, null, null, input.images()));
        String text = extractedText(fetched);
        if (!hasText(text)) {
            throw new IllegalArgumentException("未能从图片中识别出可用的攻略文字，请确认截图清晰且包含正文后重试。");
        }
        String sourceName = fetched != null && fetched.normalizedDocument() != null
                && hasText(fetched.normalizedDocument().sourceName())
                ? fetched.normalizedDocument().sourceName() : "图片OCR导入";
        String title = hasText(input.title()) ? input.title().trim() : "图片攻略";
        String sourceUrl = fetched != null && hasText(fetched.sourceUrl())
                ? fetched.sourceUrl() : null;
        return new ResolvedSource(text, title, sourceName, sourceUrl, null);
    }

    private ResolvedSource resolveVideoLink(ImportInput input, String type) {
        String url = require(input.sourceUrl(), "视频链接");
        String platform = "XIAOHONGSHU_VIDEO".equals(type) ? "小红书" : "抖音";
        FetchedGuide fetched = guideClient.fetch(new GuideImportRequest(
                url, "PUBLIC_GUIDE_URL", null, null, null, null, null, null));
        String text = extractedText(fetched);
        if (!hasText(text) || videoTextTooThin(text)) {
            throw new IllegalArgumentException(
                    "已识别为" + platform + "链接，但该页面正文无法抓取到可用的攻略内容"
                    + "（抖音/小红书正文多为客户端渲染）。请在客户端打开内容复制简介文字，"
                    + "改用「粘贴正文」导入" + (platform.equals("小红书") ? "（小红书亦可直接粘贴分享文本）。" : "。"));
        }
        String title = hasText(input.title()) ? input.title().trim()
                : (fetched != null && hasText(fetched.title()) ? fetched.title() : platform + "攻略");
        String sourceName = hasText(input.sourceName()) ? input.sourceName().trim()
                : platform + "链接";
        String sourceUrl = fetched != null && hasText(fetched.finalUrl())
                ? fetched.finalUrl() : url;
        return new ResolvedSource(text, title, sourceName, sourceUrl, null);
    }

    private static String extractedText(FetchedGuide fetched) {
        if (fetched == null) {
            return null;
        }
        if (fetched.normalizedDocument() != null && hasText(fetched.normalizedDocument().content())) {
            return fetched.normalizedDocument().content();
        }
        return fetched.excerpt();
    }

    /** 抖音/小红书 客户端渲染页面常只有壳文本+平台页脚；据此判定没有可用正文。 */
    static boolean videoTextTooThin(String text) {
        if (text == null) {
            return true;
        }
        String reduced = text;
        for (String marker : VIDEO_BOILERPLATE) {
            reduced = reduced.replace(marker, "");
        }
        reduced = reduced.replaceAll("\\s+", "").trim();
        return reduced.length() < 32;
    }

    private static final List<String> VIDEO_BOILERPLATE = List.of(
            "行吟信息科技", "马当路", "9501-3888", "©",
            "发现", "RED", "直播", "发布", "通知", "消息", "抖音", "登录后查看");

    private static String defaultSourceUrl(String city, String title) {
        return "https://knowledge.local/" + slugId(city, title);
    }

    private static String slugId(String city, String title) {
        String joined = (city + " " + title).toLowerCase(Locale.ROOT)
                .replaceAll("[^a-z0-9]+", "-").replaceAll("(^-+|-+$)", "");
        if (joined.length() < 3) {
            joined = "kb-" + DemoEmbedding.sha256Hex(city + title).substring(0, 12);
        }
        if (joined.length() > 80) {
            joined = joined.substring(0, 80).replaceAll("-+$", "");
        }
        return joined;
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private static String require(String value, String label) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(label + " is required");
        }
        return value.trim();
    }

    private static String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }

    private record ResolvedSource(
            String content,
            String title,
            String sourceName,
            String sourceUrl,
            String reason
    ) {
    }

    public record ImportInput(
            String city,
            String category,
            String title,
            String content,
            String sourceUrl,
            String sourceName,
            String reliabilityLevel,
            LocalDate validFrom,
            LocalDate validTo,
            String sourceType,
            List<GuideImagePayload> images,
            String contentType,
            String regionProvince,
            String regionCity,
            String regionDistrict
    ) {
    }

    public record ImportResult(String documentId, int version, String status) {
    }

    /** 编辑已有文档：仅提供需要改的字段（null/空 = 保持不变）。 */
    public record EditInput(
            String category,
            String contentType,
            String regionProvince,
            String regionCity,
            String regionDistrict,
            String sourceName,
            String reliabilityLevel,
            LocalDate validFrom,
            LocalDate validTo,
            String content
    ) {
    }

    public record KnowledgePage(List<KnowledgeRecord> items, int total, int page, int size) {
    }

    public record KnowledgeDetail(KnowledgeRecord document, List<KnowledgeChunkRecord> chunks) {
    }

    static final class NotFound extends RuntimeException {
        NotFound(String documentId) {
            super("knowledge document not found: " + documentId);
        }
    }
}