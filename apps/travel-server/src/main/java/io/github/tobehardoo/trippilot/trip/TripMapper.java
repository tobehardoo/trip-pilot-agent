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
                preferences, fixed_schedules, arrival, departure, accommodation,
                must_visit_places, avoid_places, meal_windows, mobility_level, schema_version
            ) VALUES (
                #{tripId}, #{budgetAmount}, #{travelers}, #{travelerType}, #{pace},
                CAST(#{preferencesJson} AS jsonb), CAST(#{fixedSchedulesJson} AS jsonb),
                CAST(#{arrivalJson} AS jsonb), CAST(#{departureJson} AS jsonb),
                CAST(#{accommodationJson} AS jsonb), CAST(#{mustVisitPlacesJson} AS jsonb),
                CAST(#{avoidPlacesJson} AS jsonb), CAST(#{mealWindowsJson} AS jsonb),
                #{mobilityLevel}, #{schemaVersion}
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
                   trip_constraint.arrival::text AS arrival_json,
                   trip_constraint.departure::text AS departure_json,
                   trip_constraint.accommodation::text AS accommodation_json,
                   trip_constraint.must_visit_places::text AS must_visit_places_json,
                   trip_constraint.avoid_places::text AS avoid_places_json,
                   trip_constraint.meal_windows::text AS meal_windows_json,
                   trip_constraint.mobility_level,
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
                   arrival::text AS arrival_json,
                   departure::text AS departure_json,
                   accommodation::text AS accommodation_json,
                   must_visit_places::text AS must_visit_places_json,
                   avoid_places::text AS avoid_places_json,
                   meal_windows::text AS meal_windows_json,
                   mobility_level,
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
                arrival = CAST(#{arrivalJson} AS jsonb),
                departure = CAST(#{departureJson} AS jsonb),
                accommodation = CAST(#{accommodationJson} AS jsonb),
                must_visit_places = CAST(#{mustVisitPlacesJson} AS jsonb),
                avoid_places = CAST(#{avoidPlacesJson} AS jsonb),
                meal_windows = CAST(#{mealWindowsJson} AS jsonb),
                mobility_level = #{mobilityLevel},
                schema_version = #{schemaVersion}, updated_at = CURRENT_TIMESTAMP
            WHERE trip_id = #{tripId}
            """)
    int updateConstraint(TripConstraintRecord constraint);
}
