package io.github.tobehardoo.trippilot.share;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
interface ItineraryShareMapper {

    @Insert("""
            INSERT INTO business.itinerary_share(
                id, itinerary_version_id, trip_id, owner_id, token_hash, expires_at
            ) VALUES (
                #{id}, #{itineraryVersionId}, #{tripId}, #{ownerId}, #{tokenHash}, #{expiresAt}
            )
            """)
    int insert(ShareWrite share);

    @Select("""
            SELECT version.id
            FROM business.itinerary_version version
            JOIN business.itinerary itinerary ON itinerary.id = version.itinerary_id
            JOIN business.trip trip ON trip.id = itinerary.trip_id
            WHERE version.id = #{versionId}
              AND itinerary.trip_id = #{tripId}
              AND trip.owner_id = #{ownerId}
            FOR UPDATE OF version
            """)
    Optional<UUID> findOwnedVersion(
            @Param("tripId") UUID tripId,
            @Param("versionId") UUID versionId,
            @Param("ownerId") UUID ownerId
    );

    @Select("""
            SELECT id
            FROM business.itinerary_share
            WHERE itinerary_version_id = #{versionId}
              AND trip_id = #{tripId}
              AND owner_id = #{ownerId}
              AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > #{now})
            """)
    Optional<UUID> findActiveOwnedVersion(
            @Param("tripId") UUID tripId,
            @Param("versionId") UUID versionId,
            @Param("ownerId") UUID ownerId,
            @Param("now") Instant now
    );

    @Update("""
            UPDATE business.itinerary_share
            SET revoked_at = #{revokedAt}
            WHERE itinerary_version_id = #{versionId}
              AND trip_id = #{tripId}
              AND owner_id = #{ownerId}
              AND revoked_at IS NULL
              AND expires_at IS NOT NULL
              AND expires_at <= #{revokedAt}
            """)
    int revokeExpiredOwnedVersion(
            @Param("tripId") UUID tripId,
            @Param("versionId") UUID versionId,
            @Param("ownerId") UUID ownerId,
            @Param("revokedAt") Instant revokedAt
    );

    @Select("""
            SELECT id, itinerary_version_id, trip_id, owner_id, token_hash,
                   expires_at, revoked_at, created_at
            FROM business.itinerary_share
            WHERE trip_id = #{tripId} AND owner_id = #{ownerId}
            ORDER BY created_at DESC, id
            """)
    List<ShareRecord> findOwned(@Param("tripId") UUID tripId, @Param("ownerId") UUID ownerId);

    @Select("""
            SELECT id, itinerary_version_id, trip_id, owner_id, token_hash,
                   expires_at, revoked_at, created_at
            FROM business.itinerary_share
            WHERE id = #{shareId} AND trip_id = #{tripId} AND owner_id = #{ownerId}
            """)
    Optional<ShareRecord> findOwnedById(
            @Param("shareId") UUID shareId,
            @Param("tripId") UUID tripId,
            @Param("ownerId") UUID ownerId
    );

    @Select("""
            SELECT itinerary_version_id
            FROM business.itinerary_share
            WHERE token_hash = #{tokenHash}
              AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > #{now})
            """)
    Optional<UUID> findActiveVersionByTokenHash(
            @Param("tokenHash") String tokenHash,
            @Param("now") Instant now
    );

    @Update("""
            UPDATE business.itinerary_share
            SET revoked_at = #{revokedAt}
            WHERE id = #{shareId}
              AND trip_id = #{tripId}
              AND owner_id = #{ownerId}
              AND revoked_at IS NULL
            """)
    int revoke(
            @Param("shareId") UUID shareId,
            @Param("tripId") UUID tripId,
            @Param("ownerId") UUID ownerId,
            @Param("revokedAt") Instant revokedAt
    );

    record ShareWrite(
            UUID id,
            UUID itineraryVersionId,
            UUID tripId,
            UUID ownerId,
            String tokenHash,
            Instant expiresAt
    ) {
    }

    record ShareRecord(
            UUID id,
            UUID itineraryVersionId,
            UUID tripId,
            UUID ownerId,
            String tokenHash,
            Instant expiresAt,
            Instant revokedAt,
            Instant createdAt
    ) {
    }
}
