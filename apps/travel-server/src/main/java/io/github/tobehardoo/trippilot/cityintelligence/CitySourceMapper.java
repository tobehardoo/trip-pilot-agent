package io.github.tobehardoo.trippilot.cityintelligence;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface CitySourceMapper {

    @Select("""
            <script>
            SELECT id, city_code, city_name, source_name, source_url, source_type,
                   reliability_level, enabled, parser_strategy,
                   refresh_policy::text AS refresh_policy_json,
                   review_status, review_note, reviewed_by, reviewed_at,
                   version, created_at, updated_at
            FROM business.city_source_registry
            <where>
                <if test="cityCode != null and cityCode != ''">
                    city_code = #{cityCode}
                </if>
                <if test="enabled != null">
                    AND enabled = #{enabled}
                </if>
                <if test="reviewStatus != null and reviewStatus != ''">
                    AND review_status = #{reviewStatus}
                </if>
            </where>
            ORDER BY city_code, source_type, source_name, id
            </script>
            """)
    List<CitySourceRecord> findAll(
            @Param("cityCode") String cityCode,
            @Param("enabled") Boolean enabled,
            @Param("reviewStatus") String reviewStatus
    );

    @Select("""
            SELECT id, city_code, city_name, source_name, source_url, source_type,
                   reliability_level, enabled, parser_strategy,
                   refresh_policy::text AS refresh_policy_json,
                   review_status, review_note, reviewed_by, reviewed_at,
                   version, created_at, updated_at
            FROM business.city_source_registry
            WHERE id = #{id}
            """)
    Optional<CitySourceRecord> findById(UUID id);

    @Update("""
            UPDATE business.city_source_registry
            SET enabled = #{enabled},
                review_status = #{reviewStatus},
                review_note = #{reviewNote},
                reviewed_by = #{reviewedBy},
                reviewed_at = CURRENT_TIMESTAMP,
                version = version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = #{id} AND version = #{expectedVersion}
            """)
    int updateReview(
            @Param("id") UUID id,
            @Param("enabled") boolean enabled,
            @Param("reviewStatus") String reviewStatus,
            @Param("reviewNote") String reviewNote,
            @Param("reviewedBy") UUID reviewedBy,
            @Param("expectedVersion") int expectedVersion
    );
}
