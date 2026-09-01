package io.github.tobehardoo.trippilot.cityintelligence;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface CityIntelligenceMapper {

    @Insert("""
            INSERT INTO business.city_intelligence_refresh(
                id, trip_id, city_code, idempotency_key, status,
                requested_categories, provider_diagnostics, attempt_count, version
            ) VALUES (
                #{id}, #{tripId}, #{cityCode}, #{idempotencyKey}, #{status},
                CAST(#{requestedCategoriesJson} AS jsonb),
                CAST(#{providerDiagnosticsJson} AS jsonb),
                #{attemptCount}, #{version}
            )
            ON CONFLICT DO NOTHING
            """)
    int insertRefresh(CityIntelligenceRefreshRecord refresh);

    @Select("""
            SELECT id::text
            FROM business.city_source_registry
            WHERE city_code = #{cityCode}
              AND enabled = TRUE
              AND review_status = 'APPROVED'
            ORDER BY source_type, source_name, id
            """)
    List<String> findApprovedSourceIds(String cityCode);

    @Select("""
            SELECT id, trip_id, city_code, idempotency_key, status,
                   requested_categories::text AS requested_categories_json,
                   provider_diagnostics::text AS provider_diagnostics_json,
                   attempt_count, started_at, completed_at, error_code, error_message,
                   version, created_at, updated_at
            FROM business.city_intelligence_refresh
            WHERE id = #{refreshId}
            """)
    Optional<CityIntelligenceRefreshRecord> findRefresh(UUID refreshId);

    @Select("""
            SELECT id, trip_id, city_code, idempotency_key, status,
                   requested_categories::text AS requested_categories_json,
                   provider_diagnostics::text AS provider_diagnostics_json,
                   attempt_count, started_at, completed_at, error_code, error_message,
                   version, created_at, updated_at
            FROM business.city_intelligence_refresh
            WHERE trip_id = #{tripId}
            ORDER BY created_at DESC, id
            LIMIT 1
            """)
    Optional<CityIntelligenceRefreshRecord> findLatestRefresh(UUID tripId);

    @Select("""
            SELECT id, trip_id, city_code, idempotency_key, status,
                   requested_categories::text AS requested_categories_json,
                   provider_diagnostics::text AS provider_diagnostics_json,
                   attempt_count, started_at, completed_at, error_code, error_message,
                   version, created_at, updated_at
            FROM business.city_intelligence_refresh
            WHERE trip_id = #{tripId}
              AND idempotency_key = #{idempotencyKey}
            """)
    Optional<CityIntelligenceRefreshRecord> findByIdempotencyKey(
            @Param("tripId") UUID tripId,
            @Param("idempotencyKey") UUID idempotencyKey
    );

    @Select("""
            SELECT DISTINCT trusted_fact.category
            FROM business.trusted_fact
            JOIN business.guide_import
              ON guide_import.id = trusted_fact.guide_import_id
            WHERE guide_import.trip_id = #{tripId}
              AND guide_import.source_type IN (
                  'CITY_INTELLIGENCE',
                  'OFFICIAL_TOURISM',
                  'OFFICIAL_ATTRACTION'
              )
              AND guide_import.enabled = TRUE
              AND trusted_fact.active = TRUE
              AND trusted_fact.expires_at > #{asOf}
              AND (
                  trusted_fact.effective_date IS NULL
                  OR trusted_fact.effective_date
                      BETWEEN #{startDate} AND #{endDate}
              )
            ORDER BY trusted_fact.category
            """)
    List<String> findFreshApplicableFactCategories(
            @Param("tripId") UUID tripId,
            @Param("asOf") Instant asOf,
            @Param("startDate") LocalDate startDate,
            @Param("endDate") LocalDate endDate
    );

    @Update("""
            UPDATE business.city_intelligence_refresh
            SET status = 'RUNNING',
                attempt_count = attempt_count + 1,
                started_at = COALESCE(started_at, #{startedAt}),
                error_code = NULL,
                error_message = NULL,
                version = version + 1,
                updated_at = #{startedAt}
            WHERE id = #{refreshId}
              AND status IN ('QUEUED', 'FAILED')
              AND version = #{expectedVersion}
            """)
    int markRunning(
            @Param("refreshId") UUID refreshId,
            @Param("expectedVersion") int expectedVersion,
            @Param("startedAt") Instant startedAt
    );

    @Update("""
            UPDATE business.city_intelligence_refresh
            SET status = #{status},
                provider_diagnostics = CAST(#{diagnosticsJson} AS jsonb),
                completed_at = #{completedAt},
                error_code = #{errorCode},
                error_message = #{errorMessage},
                version = version + 1,
                updated_at = #{completedAt}
            WHERE id = #{refreshId}
              AND status = 'RUNNING'
            """)
    int completeRefresh(
            @Param("refreshId") UUID refreshId,
            @Param("status") String status,
            @Param("diagnosticsJson") String diagnosticsJson,
            @Param("completedAt") Instant completedAt,
            @Param("errorCode") String errorCode,
            @Param("errorMessage") String errorMessage
    );
}
