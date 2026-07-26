package io.github.tobehardoo.trippilot.guide;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.time.Instant;

import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.FactMergeDecisionRecord;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.NormalizedDocumentRecord;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.RejectedFactRecord;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.TrustedFactRecord;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface GuideImportMapper {

    @Select("""
            SELECT id
            FROM business.trip
            WHERE id = #{tripId}
            FOR UPDATE
            """)
    Optional<UUID> lockTripForCityRefresh(UUID tripId);

    @Insert("""
            INSERT INTO business.guide_import(
                id, trip_id, source_type, source_url, final_url, source_host, title,
                excerpt, content_hash, fetched_at, enabled
            ) VALUES (
                #{id}, #{tripId}, #{sourceType}, #{sourceUrl}, #{finalUrl}, #{sourceHost}, #{title},
                #{excerpt}, #{contentHash}, #{fetchedAt}, #{enabled}
            )
            ON CONFLICT (trip_id, final_url, content_hash) DO NOTHING
            """)
    int insertImport(GuideImportRecord record);

    @Update("""
            UPDATE business.guide_import
            SET source_type = #{sourceType},
                source_url = #{sourceUrl},
                source_host = #{sourceHost},
                title = #{title},
                excerpt = #{excerpt},
                fetched_at = #{fetchedAt},
                enabled = #{enabled}
            WHERE id = #{id}
              AND trip_id = #{tripId}
            """)
    int refreshImport(GuideImportRecord record);

    @Insert("""
            INSERT INTO business.guide_fact(
                id, guide_import_id, category, statement, evidence,
                confidence, effective_date, observed_at, expires_at
            ) VALUES (
                #{id}, #{guideImportId}, #{category}, #{statement}, #{evidence},
                #{confidence}, #{effectiveDate}, #{observedAt}, #{expiresAt}
            )
            ON CONFLICT (guide_import_id, category, statement_hash) DO UPDATE
            SET evidence = EXCLUDED.evidence,
                confidence = EXCLUDED.confidence,
                observed_at = EXCLUDED.observed_at,
                expires_at = EXCLUDED.expires_at
            """)
    int upsertFact(GuideFactRecord record);

    @Insert("""
            INSERT INTO business.normalized_document(
                guide_import_id, document_id, source_type, source_name, source_url,
                city, title, content, fetched_at, content_hash, encoding, language,
                metadata, reliability_level, source_reviewed,
                model_status, model_attempts, model_failure_code, model_failure_reason
            ) VALUES (
                #{guideImportId}, #{documentId}, #{sourceType}, #{sourceName}, #{sourceUrl},
                #{city}, #{title}, #{content}, #{fetchedAt}, #{contentHash}, #{encoding},
                #{language}, CAST(#{metadataJson} AS jsonb), #{reliabilityLevel},
                #{sourceReviewed}, #{modelStatus}, #{modelAttempts},
                #{modelFailureCode}, #{modelFailureReason}
            )
            ON CONFLICT (guide_import_id, document_id) DO UPDATE
            SET source_type = EXCLUDED.source_type,
                source_name = EXCLUDED.source_name,
                source_url = EXCLUDED.source_url,
                city = EXCLUDED.city,
                title = EXCLUDED.title,
                content = EXCLUDED.content,
                fetched_at = EXCLUDED.fetched_at,
                content_hash = EXCLUDED.content_hash,
                encoding = EXCLUDED.encoding,
                language = EXCLUDED.language,
                metadata = EXCLUDED.metadata,
                reliability_level = EXCLUDED.reliability_level,
                source_reviewed = EXCLUDED.source_reviewed,
                model_status = EXCLUDED.model_status,
                model_attempts = EXCLUDED.model_attempts,
                model_failure_code = EXCLUDED.model_failure_code,
                model_failure_reason = EXCLUDED.model_failure_reason
            """)
    int upsertNormalizedDocument(NormalizedDocumentRecord record);

    @Insert("""
            INSERT INTO business.trusted_fact(
                guide_import_id, fact_id, document_id, city, category, statement,
                normalized_value, evidence, evidence_start, evidence_end, confidence,
                effective_date, checked_at, expires_at, source_type, source_name,
                source_url, reliability_level, source_reviewed, hard_constraint_eligible
            ) VALUES (
                #{guideImportId}, #{factId}, #{documentId}, #{city}, #{category},
                #{statement}, CAST(#{normalizedValueJson} AS jsonb), #{evidence},
                #{evidenceStart}, #{evidenceEnd}, #{confidence}, #{effectiveDate},
                #{checkedAt}, #{expiresAt}, #{sourceType}, #{sourceName}, #{sourceUrl},
                #{reliabilityLevel}, #{sourceReviewed}, #{hardConstraintEligible}
            )
            ON CONFLICT (guide_import_id, fact_id) DO UPDATE
            SET normalized_value = EXCLUDED.normalized_value,
                evidence = EXCLUDED.evidence,
                evidence_start = EXCLUDED.evidence_start,
                evidence_end = EXCLUDED.evidence_end,
                confidence = EXCLUDED.confidence,
                effective_date = EXCLUDED.effective_date,
                checked_at = EXCLUDED.checked_at,
                expires_at = EXCLUDED.expires_at,
                reliability_level = EXCLUDED.reliability_level,
                source_reviewed = EXCLUDED.source_reviewed,
                hard_constraint_eligible = EXCLUDED.hard_constraint_eligible,
                active = TRUE,
                updated_at = CURRENT_TIMESTAMP
            """)
    int upsertTrustedFact(TrustedFactRecord record);

    @Insert("""
            INSERT INTO business.fact_validation_rejection(
                id, guide_import_id, category, statement, reasons
            ) VALUES (
                #{id}, #{guideImportId}, #{category}, #{statement},
                CAST(#{reasonsJson} AS jsonb)
            )
            """)
    int insertRejectedFact(RejectedFactRecord record);

    @Insert("""
            INSERT INTO business.fact_merge_decision(
                id, guide_import_id, selected_fact_id, conflict_fact_ids,
                downgraded_fact_ids, decision_reason, needs_manual_review
            ) VALUES (
                #{id}, #{guideImportId}, #{selectedFactId},
                CAST(#{conflictFactIdsJson} AS jsonb),
                CAST(#{downgradedFactIdsJson} AS jsonb),
                #{decisionReason}, #{needsManualReview}
            )
            """)
    int insertFactMergeDecision(FactMergeDecisionRecord record);

    @Delete("""
            DELETE FROM business.fact_merge_decision
            WHERE guide_import_id = #{guideImportId}
            """)
    int deleteFactMergeDecisions(UUID guideImportId);

    @Delete("""
            DELETE FROM business.fact_validation_rejection
            WHERE guide_import_id = #{guideImportId}
            """)
    int deleteRejectedFacts(UUID guideImportId);

    @Update("""
            UPDATE business.trusted_fact
            SET active = FALSE, updated_at = CURRENT_TIMESTAMP
            WHERE guide_import_id = #{guideImportId}
            """)
    int deactivateTrustedFacts(UUID guideImportId);

    @Select("""
            SELECT guide_import_id, document_id, source_type, source_name, source_url,
                   city, title, content, fetched_at, content_hash, encoding, language,
                   metadata::text AS metadata_json, reliability_level, source_reviewed,
                   model_status, model_attempts, model_failure_code, model_failure_reason
            FROM business.normalized_document
            WHERE guide_import_id = #{guideImportId}
            ORDER BY created_at DESC
            LIMIT 1
            """)
    Optional<NormalizedDocumentRecord> findNormalizedDocument(UUID guideImportId);

    @Select("""
            SELECT guide_import_id, fact_id, document_id, city, category, statement,
                   normalized_value::text AS normalized_value_json,
                   evidence, evidence_start, evidence_end, confidence,
                   effective_date, checked_at, expires_at, source_type, source_name,
                   source_url, reliability_level, source_reviewed,
                   hard_constraint_eligible
            FROM business.trusted_fact
            WHERE guide_import_id = #{guideImportId} AND active = TRUE
            ORDER BY checked_at DESC, fact_id
            """)
    List<TrustedFactRecord> findTrustedFacts(UUID guideImportId);

    @Select("""
            SELECT id, guide_import_id, selected_fact_id,
                   conflict_fact_ids::text AS conflict_fact_ids_json,
                   downgraded_fact_ids::text AS downgraded_fact_ids_json,
                   decision_reason, needs_manual_review
            FROM business.fact_merge_decision
            WHERE guide_import_id = #{guideImportId}
            ORDER BY created_at, id
            """)
    List<FactMergeDecisionRecord> findFactMergeDecisions(UUID guideImportId);

    @Select("""
            SELECT id, guide_import_id, category, statement,
                   reasons::text AS reasons_json
            FROM business.fact_validation_rejection
            WHERE guide_import_id = #{guideImportId}
            ORDER BY created_at, id
            """)
    List<RejectedFactRecord> findRejectedFacts(UUID guideImportId);

    @Select("""
            SELECT id, trip_id, source_type, source_url, final_url, source_host, title,
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
            SELECT guide_import.id, guide_import.trip_id, guide_import.source_type,
                   guide_import.source_url,
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
                   confidence, effective_date, observed_at, expires_at
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

    @Update("""
            UPDATE business.guide_import
            SET enabled = FALSE
            WHERE trip_id = #{tripId}
              AND source_type = 'CITY_INTELLIGENCE'
              AND id <> #{currentImportId}
              AND enabled = TRUE
            """)
    int disableOtherCityImports(
            @Param("tripId") UUID tripId,
            @Param("currentImportId") UUID currentImportId
    );

    @Select("""
            SELECT guide_import.id, guide_import.trip_id, guide_import.source_type,
                   guide_import.source_url,
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
                   guide_import.source_type,
                   guide_import.final_url AS source_url,
                   guide_import.source_host,
                   guide_import.title AS source_title,
                   guide_fact.confidence,
                   guide_fact.effective_date,
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
