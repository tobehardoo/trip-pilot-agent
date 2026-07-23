package io.github.tobehardoo.trippilot.guide;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

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
                excerpt, content_hash, fetched_at
            ) VALUES (
                #{id}, #{tripId}, #{sourceUrl}, #{finalUrl}, #{sourceHost}, #{title},
                #{excerpt}, #{contentHash}, #{fetchedAt}
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
                   excerpt, content_hash, fetched_at, created_at
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
                   guide_import.fetched_at, guide_import.created_at
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
}
