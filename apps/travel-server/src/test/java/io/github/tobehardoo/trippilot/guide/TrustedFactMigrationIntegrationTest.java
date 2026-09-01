package io.github.tobehardoo.trippilot.guide;

import java.util.List;

import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.junit.jupiter.api.Assertions.assertEquals;

class TrustedFactMigrationIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void createsQueryableTrustedFactLifecycleTablesAndIndexes() {
        List<String> tables = jdbcTemplate.queryForList("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'business'
                  AND table_name IN (
                    'normalized_document',
                    'trusted_fact',
                    'fact_validation_rejection',
                    'fact_merge_decision',
                    'city_intelligence_refresh',
                    'city_intelligence_snapshot',
                    'planning_context_snapshot'
                  )
                ORDER BY table_name
                """, String.class);

        assertEquals(List.of(
                "city_intelligence_refresh",
                "city_intelligence_snapshot",
                "fact_merge_decision",
                "fact_validation_rejection",
                "normalized_document",
                "planning_context_snapshot",
                "trusted_fact"
        ), tables);
        Integer lifecycleIndexes = jdbcTemplate.queryForObject("""
                SELECT count(*)
                FROM pg_indexes
                WHERE schemaname = 'business'
                  AND indexname IN (
                    'trusted_fact_source_idx',
                    'trusted_fact_lifecycle_idx',
                    'trusted_fact_city_category_date_idx',
                    'city_intelligence_refresh_idempotency_idx',
                    'planning_context_snapshot_task_unique_idx'
                  )
                """, Integer.class);
        assertEquals(5, lifecycleIndexes);
    }
}
