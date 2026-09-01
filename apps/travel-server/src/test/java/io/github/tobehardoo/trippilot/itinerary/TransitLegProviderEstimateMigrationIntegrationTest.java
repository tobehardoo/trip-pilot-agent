package io.github.tobehardoo.trippilot.itinerary;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.util.UUID;

import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.assertj.core.api.Assertions.assertThat;

class TransitLegProviderEstimateMigrationIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void permitsOnlyNonemptyEstimatedAmapTaxiAsTheNewProviderEstimateCombination() {
        jdbcTemplate.execute((ConnectionCallback<Void>) connection -> {
            createProbeTable(connection);

            assertThat(canInsert(connection, "TAXI", "AMAP", true, true)).isTrue();
            assertThat(canInsert(connection, "TAXI", "AMAP", true, false)).isFalse();
            assertThat(canInsert(connection, "DRIVING", "AMAP", true, true)).isFalse();
            assertThat(canInsert(connection, "TRANSIT", "AMAP", true, true)).isFalse();
            assertThat(canInsert(connection, "TAXI", "DEMO", true, false)).isTrue();
            assertThat(canInsert(connection, "DRIVING", "AMAP", false, true)).isTrue();
            return null;
        });
    }

    private static void createProbeTable(Connection connection) throws SQLException {
        try (var statement = connection.createStatement()) {
            statement.execute("""
                    CREATE TEMP TABLE b19d_transit_leg_probe
                    (LIKE business.transit_leg INCLUDING ALL)
                    ON COMMIT PRESERVE ROWS
                    """);
        }
    }

    private static boolean canInsert(
            Connection connection,
            String mode,
            String provider,
            boolean estimated,
            boolean hasGeometry
    ) throws SQLException {
        try (var truncate = connection.createStatement()) {
            truncate.execute("TRUNCATE b19d_transit_leg_probe");
        }
        try (PreparedStatement insert = connection.prepareStatement("""
                INSERT INTO b19d_transit_leg_probe(
                    id, itinerary_day_id, leg_order, from_activity_id, to_activity_id,
                    mode, distance_meters, duration_seconds, provider, estimated, polyline
                ) VALUES (?, ?, 0, ?, ?, ?, 1000, 600, ?, ?, CAST(? AS jsonb))
                """)) {
            insert.setObject(1, UUID.randomUUID());
            insert.setObject(2, UUID.randomUUID());
            insert.setObject(3, UUID.randomUUID());
            insert.setObject(4, UUID.randomUUID());
            insert.setString(5, mode);
            insert.setString(6, provider);
            insert.setBoolean(7, estimated);
            insert.setString(8, hasGeometry
                    ? "[{\"longitude\":113.26,\"latitude\":23.13}]"
                    : "[]");
            insert.executeUpdate();
            return true;
        } catch (SQLException exception) {
            return false;
        }
    }
}
