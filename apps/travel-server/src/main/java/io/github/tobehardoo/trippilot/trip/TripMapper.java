package io.github.tobehardoo.trippilot.trip;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface TripMapper {

    @Insert("""
            INSERT INTO business.trip(id, owner_id, title, destination, start_date, end_date, status, version)
            VALUES (#{id}, #{ownerId}, #{title}, #{destination}, #{startDate}, #{endDate}, #{status}, #{version})
            """)
    int insertTrip(TripRecord trip);

    @Insert("""
            INSERT INTO business.trip_constraint(
                trip_id, budget_amount, travelers, traveler_type, pace,
                preferences, fixed_schedules, schema_version
            ) VALUES (
                #{tripId}, #{budgetAmount}, #{travelers}, #{travelerType}, #{pace},
                CAST(#{preferencesJson} AS jsonb), CAST(#{fixedSchedulesJson} AS jsonb), #{schemaVersion}
            )
            """)
    int insertConstraint(TripConstraintRecord constraint);

    @Select("""
            SELECT id, owner_id, title, destination, start_date, end_date, status, version, created_at, updated_at
            FROM business.trip
            WHERE id = #{id} AND owner_id = #{ownerId}
            """)
    Optional<TripRecord> findOwnedById(@Param("id") UUID id, @Param("ownerId") UUID ownerId);

    @Select("""
            SELECT trip.id, trip.owner_id, trip.title, trip.destination,
                   trip.start_date, trip.end_date, trip.status, trip.version,
                   trip.created_at, trip.updated_at,
                   trip_constraint.budget_amount, trip_constraint.travelers,
                   trip_constraint.traveler_type, trip_constraint.pace,
                   trip_constraint.preferences::text AS preferences_json,
                   trip_constraint.fixed_schedules::text AS fixed_schedules_json,
                   trip_constraint.schema_version
            FROM business.trip
            JOIN business.trip_constraint ON trip_constraint.trip_id = trip.id
            WHERE trip.id = #{id} AND trip.owner_id = #{ownerId}
            """)
    Optional<TripSnapshotRecord> findOwnedSnapshot(
            @Param("id") UUID id, @Param("ownerId") UUID ownerId
    );

    @Select("""
            SELECT id, owner_id, title, destination, start_date, end_date, status, version, created_at, updated_at
            FROM business.trip
            WHERE owner_id = #{ownerId}
            ORDER BY updated_at DESC, id
            """)
    List<TripRecord> findAllOwned(UUID ownerId);

    @Select("""
            SELECT trip_id, budget_amount, travelers, traveler_type, pace,
                   preferences::text AS preferences_json,
                   fixed_schedules::text AS fixed_schedules_json,
                   schema_version, updated_at
            FROM business.trip_constraint
            WHERE trip_id = #{tripId}
            """)
    Optional<TripConstraintRecord> findConstraint(UUID tripId);

    @Update("""
            UPDATE business.trip
            SET version = version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = #{id} AND owner_id = #{ownerId} AND version = #{expectedVersion}
            """)
    int incrementVersion(@Param("id") UUID id, @Param("ownerId") UUID ownerId,
                         @Param("expectedVersion") int expectedVersion);

    @Update("""
            UPDATE business.trip_constraint
            SET budget_amount = #{budgetAmount}, travelers = #{travelers},
                traveler_type = #{travelerType}, pace = #{pace},
                preferences = CAST(#{preferencesJson} AS jsonb),
                fixed_schedules = CAST(#{fixedSchedulesJson} AS jsonb),
                schema_version = #{schemaVersion}, updated_at = CURRENT_TIMESTAMP
            WHERE trip_id = #{tripId}
            """)
    int updateConstraint(TripConstraintRecord constraint);
}
