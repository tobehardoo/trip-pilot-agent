package io.github.tobehardoo.trippilot.itinerary;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface ItineraryVersionMapper {

    @Select("""
            SELECT version.id, version.version_number, version.parent_version_id,
                   version.planning_task_id, version.version_source, version.title,
                   version.estimated_total_cost, version.provider,
                   version.rollback_from_version_id, version.created_at,
                   (itinerary.current_version_id = version.id) AS current
            FROM business.itinerary_version version
            JOIN business.itinerary ON itinerary.id = version.itinerary_id
            JOIN business.trip ON trip.id = itinerary.trip_id
            WHERE itinerary.trip_id = #{tripId} AND trip.owner_id = #{ownerId}
            ORDER BY version.version_number DESC
            """)
    List<VersionSummaryRecord> findAllOwned(
            @Param("tripId") UUID tripId,
            @Param("ownerId") UUID ownerId
    );

    @Select("""
            SELECT version.id, version.itinerary_id, version.version_number,
                   version.parent_version_id, version.title,
                   version.estimated_total_cost, version.provider,
                   version.constraint_snapshot::text AS constraint_snapshot_json,
                   version.created_at
            FROM business.itinerary_version version
            JOIN business.itinerary ON itinerary.id = version.itinerary_id
            JOIN business.trip ON trip.id = itinerary.trip_id
            WHERE version.id = #{versionId}
              AND itinerary.trip_id = #{tripId}
              AND trip.owner_id = #{ownerId}
            """)
    Optional<ItineraryMapper.StoredVersion> findOwnedVersion(
            @Param("tripId") UUID tripId,
            @Param("versionId") UUID versionId,
            @Param("ownerId") UUID ownerId
    );

    @Select("""
            SELECT itinerary.id, itinerary.trip_id, itinerary.current_version_id,
                   current_version.version_number AS current_version_number
            FROM business.itinerary
            JOIN business.trip ON trip.id = itinerary.trip_id
            JOIN business.itinerary_version current_version
              ON current_version.id = itinerary.current_version_id
            WHERE itinerary.trip_id = #{tripId} AND trip.owner_id = #{ownerId}
            FOR UPDATE OF itinerary
            """)
    Optional<ItineraryMapper.ItineraryState> lockOwnedState(
            @Param("tripId") UUID tripId,
            @Param("ownerId") UUID ownerId
    );

    @Insert("""
            INSERT INTO business.itinerary_version(
                id, itinerary_id, version_number, parent_version_id,
                planning_task_id, version_source, title, estimated_total_cost,
                provider, constraint_snapshot, rollback_from_version_id, created_at
            ) VALUES (
                #{id}, #{itineraryId}, #{versionNumber}, #{parentVersionId},
                NULL, 'ROLLBACK', #{title}, #{estimatedTotalCost}, #{provider},
                CAST(#{constraintSnapshotJson} AS jsonb), #{rollbackFromVersionId},
                #{createdAt}
            )
            """)
    int insertRollbackVersion(RollbackVersionWrite version);

    @Select("""
            SELECT rollback.source_version_id, rollback.result_version_id,
                   result.parent_version_id AS expected_current_version_id
            FROM business.itinerary_rollback rollback
            JOIN business.itinerary_version result
              ON result.id = rollback.result_version_id
            WHERE rollback.itinerary_id = #{itineraryId}
              AND rollback.idempotency_key = #{idempotencyKey}
            """)
    Optional<RollbackResultRecord> findRollbackResult(
            @Param("itineraryId") UUID itineraryId,
            @Param("idempotencyKey") UUID idempotencyKey
    );

    @Insert("""
            INSERT INTO business.itinerary_rollback(
                id, itinerary_id, source_version_id, result_version_id,
                owner_id, idempotency_key
            ) VALUES (
                #{id}, #{itineraryId}, #{sourceVersionId}, #{resultVersionId},
                #{ownerId}, #{idempotencyKey}
            )
            """)
    int insertRollback(RollbackAuditWrite rollback);

    record VersionSummaryRecord(
            UUID id,
            int versionNumber,
            UUID parentVersionId,
            UUID planningTaskId,
            String versionSource,
            String title,
            BigDecimal estimatedTotalCost,
            String provider,
            UUID rollbackFromVersionId,
            Instant createdAt,
            boolean current
    ) {
    }

    record RollbackVersionWrite(
            UUID id,
            UUID itineraryId,
            int versionNumber,
            UUID parentVersionId,
            String title,
            BigDecimal estimatedTotalCost,
            String provider,
            String constraintSnapshotJson,
            UUID rollbackFromVersionId,
            Instant createdAt
    ) {
    }

    record RollbackAuditWrite(
            UUID id,
            UUID itineraryId,
            UUID sourceVersionId,
            UUID resultVersionId,
            UUID ownerId,
            UUID idempotencyKey
    ) {
    }

    record RollbackResultRecord(
            UUID sourceVersionId,
            UUID resultVersionId,
            UUID expectedCurrentVersionId
    ) {
    }
}
