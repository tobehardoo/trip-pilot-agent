package io.github.tobehardoo.trippilot.identity;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface RefreshTokenMapper {

    @Insert("""
            INSERT INTO business.refresh_token(id, user_id, token_hash, expires_at)
            VALUES (#{id}, #{userId}, #{tokenHash}, #{expiresAt})
            """)
    int insert(RefreshTokenRecord token);

    @Select("""
            SELECT id, user_id, token_hash, expires_at, revoked_at
            FROM business.refresh_token
            WHERE token_hash = #{tokenHash}
            FOR UPDATE
            """)
    Optional<RefreshTokenRecord> findByHashForUpdate(String tokenHash);

    @Update("""
            UPDATE business.refresh_token
            SET revoked_at = #{revokedAt}, replaced_by = #{replacementId}
            WHERE id = #{id} AND revoked_at IS NULL
            """)
    int revoke(@Param("id") UUID id, @Param("revokedAt") Instant revokedAt,
               @Param("replacementId") UUID replacementId);
}
