package io.github.tobehardoo.trippilot.userconfig;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import io.github.tobehardoo.trippilot.userconfig.UserApiConfigRow;

/** 用户自建第三方 API 配置读写。 */
@Mapper
public interface UserApiConfigMapper {

    @Select("""
            SELECT provider, api_key, api_base_url, model, updated_at
            FROM user_api_config
            WHERE user_id = #{userId}
            ORDER BY provider
            """)
    List<UserApiConfigRow> list(@Param("userId") UUID userId);

    @Insert("""
            INSERT INTO user_api_config (user_id, provider, api_key, api_base_url, model, updated_at)
            VALUES (#{userId}, #{provider}, #{apiKey}, #{apiBaseUrl}, #{model}, #{updatedAt})
            ON CONFLICT (user_id, provider) DO UPDATE SET
                api_key = EXCLUDED.api_key,
                api_base_url = EXCLUDED.api_base_url,
                model = EXCLUDED.model,
                updated_at = EXCLUDED.updated_at
            """)
    int upsert(@Param("userId") UUID userId,
               @Param("provider") String provider,
               @Param("apiKey") String apiKey,
               @Param("apiBaseUrl") String apiBaseUrl,
               @Param("model") String model,
               @Param("updatedAt") Instant updatedAt);

    @Delete("""
            DELETE FROM user_api_config WHERE user_id = #{userId} AND provider = #{provider}
            """)
    int delete(@Param("userId") UUID userId, @Param("provider") String provider);
}