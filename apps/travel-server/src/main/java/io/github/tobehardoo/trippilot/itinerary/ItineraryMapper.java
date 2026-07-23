package io.github.tobehardoo.trippilot.itinerary;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface ItineraryMapper {

    @Insert("""
            INSERT INTO business.itinerary(id, trip_id)
            VALUES (#{id}, #{tripId})
            ON CONFLICT (trip_id) DO NOTHING
            """)
    int insertItinerary(@Param("id") UUID id, @Param("tripId") UUID tripId);

    @Select("""
            SELECT itinerary.id, itinerary.trip_id, itinerary.current_version_id,
                   COALESCE(current_version.version_number, 0) AS current_version_number
            FROM business.itinerary
            LEFT JOIN business.itinerary_version AS current_version
              ON current_version.id = itinerary.current_version_id
            WHERE itinerary.trip_id = #{tripId}
            FOR UPDATE OF itinerary
            """)
    Optional<ItineraryState> findStateForUpdate(UUID tripId);

    @Insert("""
            INSERT INTO business.itinerary_version(
                id, itinerary_id, version_number, parent_version_id, planning_task_id,
                title, estimated_total_cost, provider, constraint_snapshot, created_at
            ) VALUES (
                #{id}, #{itineraryId}, #{versionNumber}, #{parentVersionId}, #{planningTaskId},
                #{title}, #{estimatedTotalCost}, #{provider},
                CAST(#{constraintSnapshotJson} AS jsonb), #{createdAt}
            )
            """)
    int insertVersion(VersionWrite version);

    @Insert("""
            INSERT INTO business.itinerary_day(id, itinerary_version_id, day_date, day_index)
            VALUES (#{id}, #{itineraryVersionId}, #{date}, #{dayIndex})
            """)
    int insertDay(DayWrite day);

    @Insert("""
            INSERT INTO business.activity(
                id, itinerary_day_id, activity_order, title,
                start_time, end_time, estimated_cost, source,
                provider_poi_id, longitude, latitude, address
            ) VALUES (
                #{id}, #{itineraryDayId}, #{activityOrder}, #{title},
                #{startTime}, #{endTime}, #{estimatedCost}, #{source},
                #{providerPoiId}, #{longitude}, #{latitude}, #{address}
            )
            """)
    int insertActivity(ActivityWrite activity);

    @Insert("""
            INSERT INTO business.transit_leg(
                id, itinerary_day_id, leg_order, from_activity_id, to_activity_id,
                mode, distance_meters, duration_seconds, provider, estimated, polyline
            ) VALUES (
                #{id}, #{itineraryDayId}, #{legOrder}, #{fromActivityId}, #{toActivityId},
                #{mode}, #{distanceMeters}, #{durationSeconds}, #{provider}, #{estimated},
                CAST(#{polylineJson} AS jsonb)
            )
            """)
    int insertTransitLeg(TransitLegWrite transitLeg);

    @Insert("""
            INSERT INTO business.itinerary_version_knowledge(
                itinerary_version_id, status, query, freshness_status,
                freshness_checked_at, stale_reason, message
            ) VALUES (
                #{itineraryVersionId}, #{status}, #{query}, #{freshnessStatus},
                #{freshnessCheckedAt}, #{staleReason}, #{message}
            )
            """)
    int insertKnowledge(KnowledgeWrite knowledge);

    @Insert("""
            INSERT INTO business.itinerary_knowledge_citation(
                id, itinerary_version_id, citation_order, document_id, document_version,
                chunk_id, chunk_index, title, source_url, source_name, collected_at,
                reliability_level, similarity
            ) VALUES (
                #{id}, #{itineraryVersionId}, #{citationOrder}, #{documentId}, #{documentVersion},
                #{chunkId}, #{chunkIndex}, #{title}, #{sourceUrl}, #{sourceName}, #{collectedAt},
                #{reliabilityLevel}, #{similarity}
            )
            """)
    int insertKnowledgeCitation(KnowledgeCitationWrite citation);

    @Update("""
            UPDATE business.itinerary
            SET current_version_id = #{versionId}, updated_at = CURRENT_TIMESTAMP
            WHERE id = #{itineraryId}
            """)
    int updateCurrentVersion(@Param("itineraryId") UUID itineraryId,
                             @Param("versionId") UUID versionId);

    @Select("""
            SELECT itinerary_version.id, itinerary_version.version_number,
                   itinerary_version.parent_version_id, itinerary_version.title,
                   itinerary_version.estimated_total_cost, itinerary_version.provider,
                   itinerary_version.created_at
            FROM business.itinerary
            JOIN business.trip ON trip.id = itinerary.trip_id
            JOIN business.itinerary_version
              ON itinerary_version.id = itinerary.current_version_id
            WHERE itinerary.trip_id = #{tripId} AND trip.owner_id = #{ownerId}
            """)
    Optional<CurrentVersion> findCurrentVersionOwned(
            @Param("tripId") UUID tripId, @Param("ownerId") UUID ownerId
    );

    @Select("""
            SELECT id, day_date AS date, day_index
            FROM business.itinerary_day
            WHERE itinerary_version_id = #{versionId}
            ORDER BY day_index
            """)
    List<StoredDay> findDays(UUID versionId);

    @Select("""
            SELECT id, activity_order, title, start_time, end_time, estimated_cost, source,
                   provider_poi_id, longitude, latitude, address
            FROM business.activity
            WHERE itinerary_day_id = #{dayId}
            ORDER BY activity_order
            """)
    List<StoredActivity> findActivities(UUID dayId);

    @Select("""
            SELECT id, leg_order, from_activity_id, to_activity_id, mode,
                   distance_meters, duration_seconds, provider, estimated,
                   polyline::text AS polyline_json
            FROM business.transit_leg
            WHERE itinerary_day_id = #{dayId}
            ORDER BY leg_order
            """)
    List<StoredTransitLeg> findTransitLegs(UUID dayId);

    @Select("""
            SELECT itinerary_version_id, status, query, freshness_status,
                   freshness_checked_at, stale_reason, message
            FROM business.itinerary_version_knowledge
            WHERE itinerary_version_id = #{versionId}
            """)
    Optional<StoredKnowledge> findKnowledge(UUID versionId);

    @Select("""
            SELECT document_id, document_version, chunk_id, chunk_index, title,
                   source_url, source_name, collected_at, reliability_level, similarity
            FROM business.itinerary_knowledge_citation
            WHERE itinerary_version_id = #{versionId}
            ORDER BY citation_order
            """)
    List<StoredKnowledgeCitation> findKnowledgeCitations(UUID versionId);

    record ItineraryState(
            UUID id,
            UUID tripId,
            UUID currentVersionId,
            int currentVersionNumber
    ) {
    }

    record VersionWrite(
            UUID id,
            UUID itineraryId,
            int versionNumber,
            UUID parentVersionId,
            UUID planningTaskId,
            String title,
            BigDecimal estimatedTotalCost,
            String provider,
            String constraintSnapshotJson,
            Instant createdAt
    ) {
    }

    record DayWrite(UUID id, UUID itineraryVersionId, LocalDate date, int dayIndex) {
    }

    record ActivityWrite(
            UUID id,
            UUID itineraryDayId,
            int activityOrder,
            String title,
            OffsetDateTime startTime,
            OffsetDateTime endTime,
            BigDecimal estimatedCost,
            String source,
            String providerPoiId,
            BigDecimal longitude,
            BigDecimal latitude,
            String address
    ) {
    }

    record TransitLegWrite(
            UUID id,
            UUID itineraryDayId,
            int legOrder,
            UUID fromActivityId,
            UUID toActivityId,
            String mode,
            int distanceMeters,
            int durationSeconds,
            String provider,
            boolean estimated,
            String polylineJson
    ) {
    }

    record KnowledgeWrite(
            UUID itineraryVersionId,
            String status,
            String query,
            String freshnessStatus,
            OffsetDateTime freshnessCheckedAt,
            String staleReason,
            String message
    ) {
    }

    record KnowledgeCitationWrite(
            UUID id,
            UUID itineraryVersionId,
            int citationOrder,
            String documentId,
            int documentVersion,
            String chunkId,
            int chunkIndex,
            String title,
            String sourceUrl,
            String sourceName,
            OffsetDateTime collectedAt,
            String reliabilityLevel,
            double similarity
    ) {
    }

    record CurrentVersion(
            UUID id,
            int versionNumber,
            UUID parentVersionId,
            String title,
            BigDecimal estimatedTotalCost,
            String provider,
            Instant createdAt
    ) {
    }

    record StoredDay(UUID id, LocalDate date, int dayIndex) {
    }

    record StoredActivity(
            UUID id,
            int activityOrder,
            String title,
            OffsetDateTime startTime,
            OffsetDateTime endTime,
            BigDecimal estimatedCost,
            String source,
            String providerPoiId,
            BigDecimal longitude,
            BigDecimal latitude,
            String address
    ) {
    }

    record StoredTransitLeg(
            UUID id,
            int legOrder,
            UUID fromActivityId,
            UUID toActivityId,
            String mode,
            int distanceMeters,
            int durationSeconds,
            String provider,
            boolean estimated,
            String polylineJson
    ) {
    }

    record StoredKnowledge(
            UUID itineraryVersionId,
            String status,
            String query,
            String freshnessStatus,
            OffsetDateTime freshnessCheckedAt,
            String staleReason,
            String message
    ) {
    }

    record StoredKnowledgeCitation(
            String documentId,
            int documentVersion,
            String chunkId,
            int chunkIndex,
            String title,
            String sourceUrl,
            String sourceName,
            OffsetDateTime collectedAt,
            String reliabilityLevel,
            double similarity
    ) {
    }
}
