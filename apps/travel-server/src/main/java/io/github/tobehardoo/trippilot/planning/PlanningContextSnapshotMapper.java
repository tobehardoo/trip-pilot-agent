package io.github.tobehardoo.trippilot.planning;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface PlanningContextSnapshotMapper {

    @Insert("""
            INSERT INTO business.planning_context_snapshot(
                id, trip_id, planning_task_id, city_intelligence_snapshot_id,
                schema_version, city, travel_start_date, travel_end_date,
                generated_at, stale, sources, facts, conflicts, excluded_facts,
                diagnostics, content_digest
            ) VALUES (
                #{id}, #{tripId}, #{planningTaskId}, #{cityIntelligenceSnapshotId},
                #{schemaVersion}, #{city}, #{travelStartDate}, #{travelEndDate},
                #{generatedAt}, #{stale}, CAST(#{sourcesJson} AS jsonb),
                CAST(#{factsJson} AS jsonb), CAST(#{conflictsJson} AS jsonb),
                CAST(#{excludedFactsJson} AS jsonb),
                CAST(#{diagnosticsJson} AS jsonb), #{contentDigest}
            )
            """)
    int insert(PlanningContextSnapshotRecord snapshot);
}
