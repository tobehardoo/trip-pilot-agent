package io.github.tobehardoo.trippilot.knowledge;

import java.util.List;
import java.util.Optional;

import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/** 知识库（agent.knowledge_*）读写，复用共享 Postgres 数据源。 */
@Mapper
public interface KnowledgeMapper {

    String DOC_COLUMNS =
            "d.document_id, d.title, d.city, d.category, d.version, "
            + "d.source_url, d.source_name, d.reliability_level, d.collected_at, "
            + "d.valid_from, d.valid_to, d.content_hash AS content_hash, "
            + "d.content_type AS content_type, "
            + "d.region_province AS region_province, d.region_city AS region_city, "
            + "d.region_district AS region_district, "
            + "array_to_string(d.applicable_seasons, ',') AS applicable_seasons, "
            + "array_to_string(d.traveler_types, ',') AS traveler_types, d.content, "
            + "(SELECT COUNT(*) FROM agent.knowledge_chunk c "
            + " WHERE c.document_id = d.document_id AND c.document_version = d.version) AS chunk_count";

    String LIST_SQL =
            "SELECT " + DOC_COLUMNS
            + " FROM agent.knowledge_document d "
            + "JOIN (SELECT document_id, MAX(version) AS version FROM agent.knowledge_document GROUP BY document_id) v "
            + "ON v.document_id = d.document_id AND v.version = d.version "
            + "WHERE (CAST(#{city} AS TEXT) IS NULL OR d.city = CAST(#{city} AS TEXT)) "
            + "AND (CAST(#{keyword} AS TEXT) IS NULL "
            + " OR d.title ILIKE CONCAT('%', CAST(#{keyword} AS TEXT), '%') "
            + " OR d.city ILIKE CONCAT('%', CAST(#{keyword} AS TEXT), '%') "
            + " OR d.content ILIKE CONCAT('%', CAST(#{keyword} AS TEXT), '%')) "
            + "ORDER BY d.collected_at DESC, d.document_id LIMIT #{limit} OFFSET #{offset}";

    String COUNT_SQL =
            "SELECT COUNT(*) FROM agent.knowledge_document d "
            + "JOIN (SELECT document_id, MAX(version) AS version FROM agent.knowledge_document GROUP BY document_id) v "
            + "ON v.document_id = d.document_id AND v.version = d.version "
            + "WHERE (CAST(#{city} AS TEXT) IS NULL OR d.city = CAST(#{city} AS TEXT)) "
            + "AND (CAST(#{keyword} AS TEXT) IS NULL "
            + " OR d.title ILIKE CONCAT('%', CAST(#{keyword} AS TEXT), '%') "
            + " OR d.city ILIKE CONCAT('%', CAST(#{keyword} AS TEXT), '%') "
            + " OR d.content ILIKE CONCAT('%', CAST(#{keyword} AS TEXT), '%'))";

    String FIND_LATEST_SQL =
            "SELECT " + DOC_COLUMNS
            + " FROM agent.knowledge_document d "
            + "WHERE d.document_id = #{documentId} ORDER BY d.version DESC LIMIT 1";

    @Select(LIST_SQL)
    List<KnowledgeRecord> list(
            @Param("city") String city,
            @Param("keyword") String keyword,
            @Param("offset") int offset,
            @Param("limit") int limit
    );

    @Select(COUNT_SQL)
    long count(@Param("city") String city, @Param("keyword") String keyword);

    @Select(FIND_LATEST_SQL)
    Optional<KnowledgeRecord> findLatest(@Param("documentId") String documentId);

    @Select("""
            SELECT c.chunk_id, c.chunk_index,
                   array_to_string(c.heading_path, ',') AS heading_path,
                   c.content_type, c.chunk_content AS content
            FROM agent.knowledge_chunk c
            WHERE c.document_id = #{documentId} AND c.document_version = #{version}
            ORDER BY c.chunk_index ASC
            """)
    List<KnowledgeChunkRecord> chunks(@Param("documentId") String documentId, @Param("version") int version);

    @Select("""
            SELECT MAX(version) FROM agent.knowledge_document WHERE document_id = #{documentId}
            """)
    Integer maxVersion(@Param("documentId") String documentId);

    @Select("""
            SELECT content_hash FROM agent.knowledge_document
            WHERE document_id = #{documentId} AND version = #{version}
            """)
    Optional<String> contentHash(@Param("documentId") String documentId, @Param("version") int version);

    @Update("""
            UPDATE agent.knowledge_document SET
                category = #{category},
                content_type = #{contentType},
                region_province = #{regionProvince},
                region_city = #{regionCity},
                region_district = #{regionDistrict},
                source_name = #{sourceName},
                reliability_level = #{reliabilityLevel},
                valid_from = #{validFrom},
                valid_to = #{validTo}
            WHERE document_id = #{documentId} AND version = #{version}
            """)
    int updateDocumentMetadata(
            @Param("documentId") String documentId,
            @Param("version") int version,
            @Param("category") String category,
            @Param("contentType") String contentType,
            @Param("regionProvince") String regionProvince,
            @Param("regionCity") String regionCity,
            @Param("regionDistrict") String regionDistrict,
            @Param("sourceName") String sourceName,
            @Param("reliabilityLevel") String reliabilityLevel,
            java.time.LocalDate validFrom,
            java.time.LocalDate validTo
    );

    @Insert("""
            INSERT INTO agent.knowledge_document (
                document_id, version, city, category, title, content, content_hash, version_fingerprint,
                source_url, source_name, published_at, collected_at, valid_from, valid_to,
                applicable_seasons, traveler_types, reliability_level,
                content_type, region_province, region_city, region_district
            ) VALUES (
                #{documentId}, #{version}, #{city}, #{category}, #{title}, #{content}, #{contentHash}, #{contentHash},
                #{sourceUrl}, #{sourceName}, NULL, #{collectedAt}, #{validFrom}, #{validTo},
                CAST(#{applicableSeasons} AS text[]), CAST(#{travelerTypes} AS text[]), #{reliabilityLevel},
                #{contentType}, #{regionProvince}, #{regionCity}, #{regionDistrict}
            )
            """)
    int insertDocument(KnowledgeRecord doc);

    @Insert("""
            INSERT INTO agent.knowledge_chunk (
                chunk_id, document_id, document_version, chunk_index, heading_path,
                chunk_content, content_hash, token_count, metadata, content_type
            ) VALUES (
                #{chunkId}, #{documentId}, #{version}, #{chunkIndex},
                CAST(#{headingPath} AS text[]),
                #{content}, #{contentHash}, #{tokenCount}, CAST('{}' AS jsonb), #{contentType}
            )
            """)
    int insertChunk(@Param("chunkId") String chunkId,
                    @Param("documentId") String documentId,
                    @Param("version") int version,
                    @Param("chunkIndex") int chunkIndex,
                    @Param("headingPath") String headingPath,
                    @Param("contentType") String contentType,
                    @Param("content") String content,
                    @Param("contentHash") String contentHash,
                    @Param("tokenCount") int tokenCount);

    @Insert("""
            INSERT INTO agent.knowledge_chunk_embedding (
                chunk_id, embedding_model, embedding_dimensions, embedding
            ) VALUES (
                #{chunkId}, #{embeddingModel}, #{embeddingDimensions},
                CAST(#{embedding} AS vector)
            )
            ON CONFLICT (chunk_id, embedding_model, embedding_dimensions) DO NOTHING
            """)
    int insertEmbedding(@Param("chunkId") String chunkId,
                        @Param("embeddingModel") String embeddingModel,
                        @Param("embeddingDimensions") int embeddingDimensions,
                        @Param("embedding") String embedding);

    /** 删除该文档的所有分块（级联删除 embedding）。 */
    @Delete("""
            DELETE FROM agent.knowledge_chunk WHERE document_id = #{documentId}
            """)
    int deleteChunks(@Param("documentId") String documentId);

    @Delete("""
            DELETE FROM agent.knowledge_document WHERE document_id = #{documentId}
            """)
    int deleteDocument(@Param("documentId") String documentId);

    @Select("""
            WITH scored AS (
                SELECT c.chunk_id, c.document_id, c.chunk_content AS content,
                       d.title, d.city, d.category, d.content_type,
                       d.region_province, d.region_city, d.region_district,
                       d.reliability_level, d.source_url, d.source_name, d.collected_at,
                       1 - (e.embedding <=> CAST(#{embedding} AS vector)) AS similarity
                FROM agent.knowledge_chunk c
                JOIN agent.knowledge_document d
                  ON d.document_id = c.document_id AND d.version = c.document_version
                JOIN agent.knowledge_chunk_embedding e ON e.chunk_id = c.chunk_id
                WHERE e.embedding_model = #{embeddingModel}
                  AND e.embedding_dimensions = #{embeddingDimensions}
                  AND (CAST(#{city} AS TEXT) IS NULL OR d.city = CAST(#{city} AS TEXT))
                  AND (CAST(#{regionProvince} AS TEXT) IS NULL
                       OR d.region_province = CAST(#{regionProvince} AS TEXT))
                  AND (CAST(#{regionCity} AS TEXT) IS NULL
                       OR d.region_city = CAST(#{regionCity} AS TEXT))
                  AND (CAST(#{regionDistrict} AS TEXT) IS NULL
                       OR d.region_district = CAST(#{regionDistrict} AS TEXT))
                  AND (CAST(#{category} AS TEXT) IS NULL OR d.category = CAST(#{category} AS TEXT))
                  AND (CAST(#{contentType} AS TEXT) IS NULL
                       OR d.content_type = CAST(#{contentType} AS TEXT))
                  AND (CAST(#{reliability} AS TEXT) IS NULL
                       OR d.reliability_level = CAST(#{reliability} AS TEXT))
                  AND 1 - (e.embedding <=> CAST(#{embedding} AS vector)) >= CAST(#{minSimilarity} AS DOUBLE PRECISION)
            ),
            ranked AS (
                SELECT scored.*,
                       row_number() OVER (
                           PARTITION BY document_id
                           ORDER BY similarity DESC
                       ) AS rn
                FROM scored
            )
            SELECT chunk_id, document_id, title, city, category, content_type,
                   region_city, region_district, source_url, source_name,
                   reliability_level, collected_at, content, similarity
            FROM ranked
            WHERE rn <= #{topKPerDocument}
            ORDER BY similarity DESC
            LIMIT #{limit}
            """)
    List<KnowledgeCitationRecord> search(
            @Param("embedding") String embedding,
            @Param("embeddingModel") String embeddingModel,
            @Param("embeddingDimensions") int embeddingDimensions,
            @Param("city") String city,
            @Param("regionProvince") String regionProvince,
            @Param("regionCity") String regionCity,
            @Param("regionDistrict") String regionDistrict,
            @Param("category") String category,
            @Param("contentType") String contentType,
            @Param("reliability") String reliability,
            @Param("minSimilarity") double minSimilarity,
            @Param("topKPerDocument") int topKPerDocument,
            @Param("limit") int limit
    );
}