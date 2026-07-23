package io.github.tobehardoo.trippilot.planning;

import java.util.Optional;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface PlanningTaskMapper {

    @Insert("""
            INSERT INTO business.planning_task(
                id, trip_id, idempotency_key, task_type, status,
                baseline_trip_version, constraint_snapshot, trace_id, retry_count, version
            ) VALUES (
                #{id}, #{tripId}, #{idempotencyKey}, #{taskType}, #{status},
                #{baselineTripVersion}, CAST(#{constraintSnapshotJson} AS jsonb),
                #{traceId}, #{retryCount}, #{version}
            )
            ON CONFLICT DO NOTHING
            """)
    int insert(PlanningTaskRecord task);

    @Select("""
            SELECT planning_task.id, planning_task.trip_id, planning_task.idempotency_key,
                   planning_task.task_type, planning_task.status, planning_task.baseline_trip_version,
                   planning_task.constraint_snapshot::text AS constraint_snapshot_json,
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

    @Select("""
            SELECT planning_task.id, planning_task.trip_id, planning_task.idempotency_key,
                   planning_task.task_type, planning_task.status, planning_task.baseline_trip_version,
                   planning_task.constraint_snapshot::text AS constraint_snapshot_json,
                   planning_task.trace_id, planning_task.retry_count, planning_task.error_code,
                   planning_task.error_message, planning_task.version,
                   planning_task.created_at, planning_task.updated_at
            FROM business.planning_task
            JOIN business.trip ON trip.id = planning_task.trip_id
            WHERE planning_task.id = #{taskId} AND trip.owner_id = #{ownerId}
            """)
    Optional<PlanningTaskRecord> findOwnedById(
            @Param("taskId") UUID taskId, @Param("ownerId") UUID ownerId
    );

    @Select("""
            SELECT planning_task.id, planning_task.trip_id, planning_task.status,
                   planning_task.baseline_trip_version, planning_task.trace_id,
                   planning_task.version AS task_version,
                   planning_task.constraint_snapshot::text AS constraint_snapshot_json,
                   trip.version AS current_trip_version,
                   trip.start_date AS trip_start_date,
                   trip.end_date AS trip_end_date,
                   planning_task.created_at
            FROM business.planning_task
            JOIN business.trip ON trip.id = planning_task.trip_id
            WHERE planning_task.id = #{taskId}
            FOR UPDATE OF planning_task, trip
            """)
    Optional<PlanningTaskCompletionRecord> findCompletionContextForUpdate(UUID taskId);

    @Update("""
            UPDATE business.planning_task
            SET status = #{status}, error_code = #{errorCode}, error_message = #{errorMessage},
                version = version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = #{taskId} AND version = #{expectedVersion}
              AND status IN ('QUEUED', 'RUNNING')
            """)
    int updateTerminalStatus(@Param("taskId") UUID taskId,
                             @Param("expectedVersion") int expectedVersion,
                             @Param("status") String status,
                             @Param("errorCode") String errorCode,
                             @Param("errorMessage") String errorMessage);

    @Update("""
            UPDATE business.planning_task
            SET status = 'CANCELLED', error_code = NULL,
                error_message = NULL, version = planning_task.version + 1,
                updated_at = CURRENT_TIMESTAMP
            FROM business.trip
            WHERE planning_task.id = #{taskId}
              AND business.trip.id = planning_task.trip_id
              AND business.trip.owner_id = #{ownerId}
              AND planning_task.status IN ('QUEUED', 'RUNNING', 'CANCELLING')
            """)
    int cancelOwned(@Param("taskId") UUID taskId, @Param("ownerId") UUID ownerId);
}
