package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface PlanningFactImpactMapper {

    @Insert("""
            INSERT INTO business.planning_fact_impact(
                id, itinerary_version_id, planning_task_id, fact_id, category,
                applicable_date, effect, target_poi_id, target_name, reason,
                source_name, source_type, source_url, reliability_level,
                checked_at, evidence, stale, conflicted, refresh_failed
            ) VALUES (
                #{id}, #{itineraryVersionId}, #{planningTaskId}, #{factId},
                #{category}, #{applicableDate}, #{effect}, #{targetPoiId},
                #{targetName}, #{reason}, #{sourceName}, #{sourceType},
                #{sourceUrl}, #{reliabilityLevel}, #{checkedAt}, #{evidence},
                #{stale}, #{conflicted}, #{refreshFailed}
            )
            """)
    int insert(PlanningFactImpactRecord impact);

    @Select("""
            SELECT id, itinerary_version_id, planning_task_id, fact_id, category,
                   applicable_date, effect, target_poi_id, target_name, reason,
                   source_name, source_type, source_url, reliability_level,
                   checked_at, evidence, stale, conflicted, refresh_failed
            FROM business.planning_fact_impact
            WHERE itinerary_version_id = #{versionId}
            ORDER BY applicable_date NULLS FIRST, id
            """)
    List<PlanningFactImpactRecord> findByVersion(UUID versionId);

    @Insert("""
            INSERT INTO business.planning_fact_impact(
                id, itinerary_version_id, planning_task_id, fact_id, category,
                applicable_date, effect, target_poi_id, target_name, reason,
                source_name, source_type, source_url, reliability_level,
                checked_at, evidence, stale, conflicted, refresh_failed, created_at
            )
            SELECT gen_random_uuid(), #{targetVersionId}, planning_task_id,
                   fact_id, category, applicable_date, effect, target_poi_id,
                   target_name, reason, source_name, source_type, source_url,
                   reliability_level, checked_at, evidence, stale,
                   conflicted, refresh_failed, created_at
            FROM business.planning_fact_impact
            WHERE itinerary_version_id = #{sourceVersionId}
            """)
    int copyToVersion(
            @Param("sourceVersionId") UUID sourceVersionId,
            @Param("targetVersionId") UUID targetVersionId
    );

    record PlanningFactImpactRecord(
            UUID id,
            UUID itineraryVersionId,
            UUID planningTaskId,
            String factId,
            String category,
            LocalDate applicableDate,
            String effect,
            String targetPoiId,
            String targetName,
            String reason,
            String sourceName,
            String sourceType,
            String sourceUrl,
            String reliabilityLevel,
            Instant checkedAt,
            String evidence,
            boolean stale,
            boolean conflicted,
            boolean refreshFailed
    ) {
    }
}
