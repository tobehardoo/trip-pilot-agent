package io.github.tobehardoo.trippilot.messaging;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface OutboxMapper {

    @Insert("""
            INSERT INTO business.outbox_event(
                id, aggregate_type, aggregate_id, event_type, routing_key,
                payload, status, retry_count, next_attempt_at
            ) VALUES (
                #{id}, #{aggregateType}, #{aggregateId}, #{eventType}, #{routingKey},
                CAST(#{payloadJson} AS jsonb), #{status}, #{retryCount}, #{nextAttemptAt}
            )
            """)
    int insert(OutboxEventRecord event);

    @Select("""
            SELECT id, aggregate_type, aggregate_id, event_type, routing_key,
                   payload::text AS payload_json, status, retry_count,
                   next_attempt_at, last_error, created_at, sent_at
            FROM business.outbox_event
            WHERE status = 'PENDING' AND next_attempt_at <= CURRENT_TIMESTAMP
            ORDER BY next_attempt_at, created_at
            LIMIT #{batchSize}
            FOR UPDATE SKIP LOCKED
            """)
    List<OutboxEventRecord> lockReadyBatch(int batchSize);

    @Update("""
            UPDATE business.outbox_event
            SET status = 'SENT', sent_at = #{sentAt}, last_error = NULL
            WHERE id = #{id} AND status = 'PENDING'
            """)
    int markSent(@Param("id") UUID id, @Param("sentAt") Instant sentAt);

    @Update("""
            UPDATE business.outbox_event
            SET retry_count = #{retryCount}, next_attempt_at = #{nextAttemptAt},
                last_error = #{lastError}
            WHERE id = #{id} AND status = 'PENDING'
            """)
    int reschedule(@Param("id") UUID id,
                   @Param("retryCount") int retryCount,
                   @Param("nextAttemptAt") Instant nextAttemptAt,
                   @Param("lastError") String lastError);
}
