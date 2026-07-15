package io.github.tobehardoo.trippilot.planning;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface PlanningTaskEventMapper {

    @Insert("""
            INSERT INTO business.planning_task_event(
                event_id, task_id, event_type, schema_version, payload, created_at
            ) VALUES (
                #{eventId}, #{taskId}, #{eventType}, #{schemaVersion},
                CAST(#{payloadJson} AS jsonb), #{createdAt}
            )
            ON CONFLICT (event_id) DO NOTHING
            """)
    int insert(PlanningTaskEventRecord event);

    @Select("""
            SELECT id, event_id, task_id, event_type, schema_version,
                   payload::text AS payload_json, created_at
            FROM business.planning_task_event
            WHERE event_id = #{eventId}
            """)
    Optional<PlanningTaskEventRecord> findByEventId(UUID eventId);

    @Select("""
            SELECT id, event_id, task_id, event_type, schema_version,
                   payload::text AS payload_json, created_at
            FROM business.planning_task_event
            WHERE task_id = #{taskId} AND id > #{afterId}
            ORDER BY id
            """)
    List<PlanningTaskEventRecord> findAfter(
            @Param("taskId") UUID taskId, @Param("afterId") long afterId
    );
}
