package io.github.tobehardoo.trippilot.agentdialog;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface AgentDialogMessageMapper {

    @Insert("""
            INSERT INTO business.agent_dialog_message(
                event_id, trip_id, run_id, event_type, schema_version, payload, created_at
            ) VALUES (
                #{eventId}, #{tripId}, #{runId}, #{eventType}, #{schemaVersion},
                CAST(#{payloadJson} AS jsonb), #{createdAt}
            )
            ON CONFLICT (event_id) DO NOTHING
            """)
    int insert(AgentDialogMessageRecord message);

    @Select("""
            SELECT id, event_id, trip_id, run_id, event_type, schema_version,
                   payload::text AS payload_json, created_at
            FROM business.agent_dialog_message
            WHERE event_id = #{eventId}
            """)
    Optional<AgentDialogMessageRecord> findByEventId(UUID eventId);

    @Select("""
            SELECT id, event_id, trip_id, run_id, event_type, schema_version,
                   payload::text AS payload_json, created_at
            FROM business.agent_dialog_message
            WHERE trip_id = #{tripId} AND id > #{afterId}
            ORDER BY id
            """)
    List<AgentDialogMessageRecord> findAfter(
            @Param("tripId") UUID tripId, @Param("afterId") long afterId
    );
}
