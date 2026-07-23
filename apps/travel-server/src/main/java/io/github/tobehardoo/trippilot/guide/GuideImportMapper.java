package io.github.tobehardoo.trippilot.guide;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.time.Instant;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface GuideImportMapper {

    @Insert("""
            INSERT INTO business.guide_import(
                id, trip_id, source_url, final_url, source_host, title,
                excerpt, content_hash, fetched_at, enabled
            ) VALUES (
                #{id}, #{tripId}, #{sourceUrl}, #{finalUrl}, #{sourceHost}, #{title},
                #{excerpt}, #{contentHash}, #{fetchedAt}, #{enabled}
            )
            ON CONFLICT (trip_id, final_url, content_hash) DO NOTHING
            """)
    int insertImport(GuideImportRecord record);

    @Update("""
            UPDATE business.guide_import
            SET source_url = #{sourceUrl},
                source_host = #{sourceHost},
                title = #{title},
                excerpt = #{excerpt},
                fetched_at = #{fetchedAt}
            WHERE id = #{id}
              AND trip_id = #{tripId}
            """)
    int refreshImport(GuideImportRecord record);

    @Insert("""
            INSERT INTO business.guide_fact(
                id, guide_import_id, category, statement, evidence,
                confidence, observed_at, expires_at
            ) VALUES (
                #{id}, #{guideImportId}, #{category}, #{statement}, #{evidence},
                #{confidence}, #{observedAt}, #{expiresAt}
            )
            ON CONFLICT (guide_import_id, category, statement_hash) DO UPDATE
            SET evidence = EXCLUDED.evidence,
                confidence = EXCLUDED.confidence,
                observed_at = EXCLUDED.observed_at,
                expires_at = EXCLUDED.expires_at
            """)
    int upsertFact(GuideFactRecord record);

    @Select("""
            SELECT id, trip_id, source_url, final_url, source_host, title,
                   excerpt, content_hash, fetched_at, enabled, created_at
            FROM business.guide_import
            WHERE trip_id = #{tripId}
              AND final_url = #{finalUrl}
              AND content_hash = #{contentHash}
            """)
    Optional<GuideImportRecord> findIdentity(
            @Param("tripId") UUID tripId,
            @Param("finalUrl") String finalUrl,
            @Param("contentHash") String contentHash
    );

    @Select("""
            SELECT guide_import.id, guide_import.trip_id, guide_import.source_url,
                   guide_import.final_url, guide_import.source_host, guide_import.title,
                   guide_import.excerpt, guide_import.content_hash,
                   guide_import.fetched_at, guide_import.enabled, guide_import.created_at
            FROM business.guide_import
            JOIN business.trip ON trip.id = guide_import.trip_id
            WHERE guide_import.trip_id = #{tripId}
              AND trip.owner_id = #{ownerId}
            ORDER BY guide_import.fetched_at DESC, guide_import.id
            """)
    List<GuideImportRecord> findAllOwned(
            @Param("tripId") UUID tripId,
            @Param("ownerId") UUID ownerId
    );

    @Select("""
            SELECT id, guide_import_id, category, statement, evidence,
                   confidence, observed_at, expires_at
            FROM business.guide_fact
            WHERE guide_import_id = #{guideImportId}
            ORDER BY created_at, id
            """)
    List<GuideFactRecord> findFacts(UUID guideImportId);

    @Update("""
            UPDATE business.guide_import
            SET enabled = #{enabled}
            WHERE id = #{guideImportId}
              AND trip_id = #{tripId}
              AND EXISTS (
                  SELECT 1
                  FROM business.trip
                  WHERE trip.id = guide_import.trip_id
                    AND trip.owner_id = #{ownerId}
              )
            """)
    int updateEnabled(
            @Param("guideImportId") UUID guideImportId,
            @Param("tripId") UUID tripId,
            @Param("ownerId") UUID ownerId,
            @Param("enabled") boolean enabled
    );

    @Select("""
            SELECT guide_import.id, guide_import.trip_id, guide_import.source_url,
                   guide_import.final_url, guide_import.source_host, guide_import.title,
                   guide_import.excerpt, guide_import.content_hash,
                   guide_import.fetched_at, guide_import.enabled, guide_import.created_at
            FROM business.guide_import
            JOIN business.trip ON trip.id = guide_import.trip_id
            WHERE guide_import.id = #{guideImportId}
              AND guide_import.trip_id = #{tripId}
              AND trip.owner_id = #{ownerId}
            """)
    Optional<GuideImportRecord> findOwnedById(
            @Param("guideImportId") UUID guideImportId,
            @Param("tripId") UUID tripId,
            @Param("ownerId") UUID ownerId
    );

    @Select("""
            SELECT guide_import.id AS guide_import_id,
                   guide_fact.id AS fact_id,
                   guide_fact.category,
                   guide_fact.statement,
                   guide_fact.evidence,
                   guide_import.final_url AS source_url,
                   guide_import.source_host,
                   guide_import.title AS source_title,
                   guide_fact.confidence,
                   guide_fact.observed_at,
                   guide_fact.expires_at
            FROM business.guide_import
            JOIN business.guide_fact ON guide_fact.guide_import_id = guide_import.id
            JOIN business.trip ON trip.id = guide_import.trip_id
            WHERE guide_import.trip_id = #{tripId}
              AND trip.owner_id = #{ownerId}
              AND guide_import.enabled = TRUE
              AND guide_fact.observed_at <= #{asOf}
              AND guide_fact.expires_at > #{asOf}
            ORDER BY guide_import.fetched_at DESC, guide_fact.confidence DESC, guide_fact.id
            LIMIT 100
            """)
    List<GuidePlanningEvidenceRecord> findFreshPlanningEvidence(
            @Param("tripId") UUID tripId,
            @Param("ownerId") UUID ownerId,
            @Param("asOf") Instant asOf
    );
}
