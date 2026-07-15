package io.github.tobehardoo.trippilot.trip;

import java.util.UUID;

import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationVersion;
import org.flywaydb.core.api.FlywayException;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.testcontainers.containers.PostgreSQLContainer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class TripPaceMigrationIntegrationTest {

    @Test
    void upgradesNullPacesBeforeEnforcingDatabaseConstraints() {
        try (PostgreSQLContainer<?> postgres = postgres()) {
            postgres.start();
            migrateToVersion(postgres, "2");
            JdbcTemplate jdbcTemplate = jdbcTemplate(postgres);
            UUID ownerId = insertOwner(jdbcTemplate, "null-pace@example.com");
            UUID tripId = UUID.randomUUID();
            insertTrip(jdbcTemplate, tripId, ownerId, "Null pace");
            insertConstraint(jdbcTemplate, tripId, null);

            migrateLatest(postgres);

            assertThat(jdbcTemplate.queryForObject(
                    "SELECT pace FROM business.trip_constraint WHERE trip_id = ?", String.class, tripId))
                    .isEqualTo("BALANCED");
            assertThatThrownBy(() -> jdbcTemplate.update(
                    "UPDATE business.trip_constraint SET pace = NULL WHERE trip_id = ?", tripId))
                    .isInstanceOf(DataAccessException.class);
            assertThatThrownBy(() -> jdbcTemplate.update(
                    "UPDATE business.trip_constraint SET pace = 'LEGACY_FAST' WHERE trip_id = ?", tripId))
                    .isInstanceOf(DataAccessException.class);
        }
    }

    @Test
    void rejectsUnknownLegacyPacesWithoutOverwritingThem() {
        try (PostgreSQLContainer<?> postgres = postgres()) {
            postgres.start();
            migrateToVersion(postgres, "2");
            JdbcTemplate jdbcTemplate = jdbcTemplate(postgres);
            UUID ownerId = insertOwner(jdbcTemplate, "unknown-pace@example.com");
            UUID tripId = UUID.randomUUID();
            insertTrip(jdbcTemplate, tripId, ownerId, "Unknown pace");
            insertConstraint(jdbcTemplate, tripId, "LEGACY_FAST");

            assertThatThrownBy(() -> migrateLatest(postgres))
                    .isInstanceOf(FlywayException.class);
            assertThat(jdbcTemplate.queryForObject(
                    "SELECT pace FROM business.trip_constraint WHERE trip_id = ?", String.class, tripId))
                    .isEqualTo("LEGACY_FAST");
        }
    }

    private PostgreSQLContainer<?> postgres() {
        return new PostgreSQLContainer<>("postgres:16-alpine")
                .withDatabaseName("trip_pilot_migration")
                .withUsername("trip_pilot")
                .withPassword("integration-test-only");
    }

    private void migrateToVersion(PostgreSQLContainer<?> postgres, String version) {
        Flyway.configure()
                .dataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword())
                .locations("classpath:db/migration")
                .target(MigrationVersion.fromVersion(version))
                .load()
                .migrate();
    }

    private void migrateLatest(PostgreSQLContainer<?> postgres) {
        Flyway.configure()
                .dataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword())
                .locations("classpath:db/migration")
                .load()
                .migrate();
    }

    private JdbcTemplate jdbcTemplate(PostgreSQLContainer<?> postgres) {
        return new JdbcTemplate(new DriverManagerDataSource(
                postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
    }

    private UUID insertOwner(JdbcTemplate jdbcTemplate, String email) {
        UUID ownerId = UUID.randomUUID();
        jdbcTemplate.update("""
                INSERT INTO business.user_account(id, email, password_hash, display_name)
                VALUES (?, ?, 'not-used-by-this-test', 'Migration Test')
                """, ownerId, email);
        return ownerId;
    }

    private void insertTrip(JdbcTemplate jdbcTemplate, UUID tripId, UUID ownerId, String title) {
        jdbcTemplate.update("""
                INSERT INTO business.trip(id, owner_id, title, destination, start_date, end_date)
                VALUES (?, ?, ?, 'Guangzhou', DATE '2026-08-01', DATE '2026-08-04')
                """, tripId, ownerId, title);
    }

    private void insertConstraint(JdbcTemplate jdbcTemplate, UUID tripId, String pace) {
        jdbcTemplate.update("""
                INSERT INTO business.trip_constraint(trip_id, travelers, traveler_type, pace)
                VALUES (?, 1, 'SOLO', ?)
                """, tripId, pace);
    }
}
