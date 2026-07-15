package io.github.tobehardoo.trippilot.planning;

import java.util.Optional;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface PlanningTaskMapper {

    @Insert("""
            INSERT INTO business.planning_task(
                id, trip_id, idempotency_key, task_type, status,
                baseline_trip_version, trace_id, retry_count, version
            ) VALUES (
                #{id}, #{tripId}, #{idempotencyKey}, #{taskType}, #{status},
                #{baselineTripVersion}, #{traceId}, #{retryCount}, #{version}
            )
            ON CONFLICT DO NOTHING
            """)
    int insert(PlanningTaskRecord task);

    @Select("""
            SELECT planning_task.id, planning_task.trip_id, planning_task.idempotency_key,
                   planning_task.task_type, planning_task.status, planning_task.baseline_trip_version,
                   planning_task.trace_id, planning_task.retry_count, planning_task.error_code,
                   planning_task.error_message, planning_task.version,
                   planning_task.created_at, planning_task.updated_at
            FROM business.planning_task
            JOIN business.trip ON trip.id = planning_task.trip_id
            WHERE planning_task.trip_id = #{tripId}
              AND planning_task.idempotency_key = #{idempotencyKey}
              AND trip.owner_id = #{ownerId}
            """)
    Optional<PlanningTaskRecord> findOwnedByIdempotencyKey(
            @Param("tripId") UUID tripId,
            @Param("idempotencyKey") UUID idempotencyKey,
            @Param("ownerId") UUID ownerId);
}
