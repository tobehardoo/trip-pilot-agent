package io.github.tobehardoo.trippilot.support;

import org.junit.jupiter.api.BeforeEach;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;

@SpringBootTest
@AutoConfigureMockMvc
public abstract class PostgresIntegrationTest {

    private static final String EXTERNAL_DATABASE_URL = System.getenv("TEST_DATABASE_URL");
    private static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:16-alpine")
            .withDatabaseName("trip_pilot")
            .withUsername("trip_pilot")
            .withPassword("integration-test-only");

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @DynamicPropertySource
    static void databaseProperties(DynamicPropertyRegistry registry) {
        if (EXTERNAL_DATABASE_URL == null || EXTERNAL_DATABASE_URL.isBlank()) {
            POSTGRES.start();
            registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
            registry.add("spring.datasource.username", POSTGRES::getUsername);
            registry.add("spring.datasource.password", POSTGRES::getPassword);
        } else {
            registry.add("spring.datasource.url", () -> EXTERNAL_DATABASE_URL);
            registry.add("spring.datasource.username", () -> requiredEnvironment("TEST_DATABASE_USERNAME"));
            registry.add("spring.datasource.password", () -> requiredEnvironment("TEST_DATABASE_PASSWORD"));
        }
        registry.add("app.security.jwt-secret", () -> "integration-test-secret-at-least-32-bytes");
        registry.add("app.security.access-token-ttl", () -> "PT15M");
        registry.add("app.security.refresh-token-ttl", () -> "P30D");
        registry.add("app.messaging.outbox-publisher-enabled", () -> "false");
    }

    @BeforeEach
    void cleanBusinessData() {
        jdbcTemplate.execute("""
                DO $$
                BEGIN
                    IF to_regclass('business.user_account') IS NOT NULL THEN
                        TRUNCATE TABLE business.outbox_event, business.planning_task,
                            business.refresh_token, business.trip_constraint,
                            business.trip, business.user_account CASCADE;
                    END IF;
                END
                $$
                """);
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException(name + " is required when TEST_DATABASE_URL is set");
        }
        return value;
    }
}
