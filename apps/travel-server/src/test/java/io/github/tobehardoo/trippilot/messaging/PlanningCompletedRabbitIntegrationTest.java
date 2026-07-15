package io.github.tobehardoo.trippilot.messaging;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.UUID;
import java.util.function.BooleanSupplier;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.support.PlanningCompletedEventFixture;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.AmqpAdmin;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageBuilder;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.containers.RabbitMQContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Testcontainers
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_CLASS)
class PlanningCompletedRabbitIntegrationTest {

    @Container
    private static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:16-alpine")
            .withDatabaseName("trip_pilot")
            .withUsername("trip_pilot")
            .withPassword("integration-test-only");

    @Container
    private static final RabbitMQContainer RABBIT = new RabbitMQContainer("rabbitmq:4.1-alpine");

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private RabbitTemplate rabbitTemplate;

    @Autowired
    private AmqpAdmin amqpAdmin;

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("spring.rabbitmq.host", RABBIT::getHost);
        registry.add("spring.rabbitmq.port", RABBIT::getAmqpPort);
        registry.add("spring.rabbitmq.username", RABBIT::getAdminUsername);
        registry.add("spring.rabbitmq.password", RABBIT::getAdminPassword);
        registry.add("app.security.jwt-secret", () -> "integration-test-secret-at-least-32-bytes");
        registry.add("app.security.access-token-ttl", () -> "PT15M");
        registry.add("app.security.refresh-token-ttl", () -> "P30D");
        registry.add("app.messaging.outbox-publisher-enabled", () -> "false");
        registry.add("app.messaging.event-consumer-enabled", () -> "true");
    }

    @BeforeEach
    void cleanState() {
        jdbcTemplate.execute("""
                TRUNCATE TABLE business.outbox_event, business.planning_task,
                    business.refresh_token, business.trip_constraint,
                    business.trip, business.user_account CASCADE
                """);
        amqpAdmin.purgeQueue(RabbitMessagingConfiguration.DEAD_LETTER_QUEUE, false);
    }

    @Test
    void consumesACompletedEventFromRabbitAndCommitsTheItinerary() throws Exception {
        PlanningContext context = createPlanningContext("rabbit-completion@example.com");
        UUID eventId = UUID.randomUUID();
        byte[] body = PlanningCompletedEventFixture.completedEvent(
                eventId, context.traceId(), context.taskId(), context.tripId()
        ).getBytes(StandardCharsets.UTF_8);

        rabbitTemplate.send(
                RabbitMessagingConfiguration.EVENT_EXCHANGE,
                "planning.completed",
                persistentJson(body)
        );

        await(Duration.ofSeconds(10), () -> "SUCCEEDED".equals(taskStatus(context.taskId())));
        assertThat(count("business.itinerary_version")).isEqualTo(1);
        assertThat(count("business.planning_task_event")).isEqualTo(2);
        assertThat(jdbcTemplate.queryForObject(
                "SELECT count(*) FROM business.planning_task_event WHERE event_id = ?",
                Integer.class, eventId
        )).isEqualTo(1);
    }

    @Test
    void deadLettersAnInvalidCompletedEventWithoutRequeue() {
        byte[] body = new byte[0];

        rabbitTemplate.send(
                RabbitMessagingConfiguration.EVENT_EXCHANGE,
                "planning.completed",
                persistentJson(body)
        );

        Message deadLetter = rabbitTemplate.receive(
                RabbitMessagingConfiguration.DEAD_LETTER_QUEUE, 10_000
        );
        assertThat(deadLetter).isNotNull();
        assertThat(deadLetter.getBody()).isEqualTo(body);
    }

    private PlanningContext createPlanningContext(String email) throws Exception {
        String token = registerAndGetAccessToken(email);
        MvcResult tripResult = mockMvc.perform(post("/api/trips")
                        .header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "title": "广州一日游",
                                  "destination": "广州",
                                  "startDate": "2026-08-01",
                                  "endDate": "2026-08-01",
                                  "constraints": {
                                    "budgetAmount": 1000,
                                    "travelers": 2,
                                    "travelerType": "FRIENDS",
                                    "pace": "BALANCED",
                                    "preferences": ["美食"],
                                    "fixedSchedules": []
                                  }
                                }
                                """))
                .andExpect(status().isCreated())
                .andReturn();
        UUID tripId = UUID.fromString(json(tripResult).get("id").asText());
        MvcResult taskResult = mockMvc.perform(post("/api/trips/{tripId}/planning-tasks", tripId)
                        .header("Authorization", bearer(token))
                        .header("Idempotency-Key", UUID.randomUUID()))
                .andExpect(status().isAccepted())
                .andReturn();
        UUID taskId = UUID.fromString(json(taskResult).get("taskId").asText());
        UUID traceId = jdbcTemplate.queryForObject(
                "SELECT trace_id FROM business.planning_task WHERE id = ?", UUID.class, taskId
        );
        return new PlanningContext(tripId, taskId, traceId);
    }

    private String registerAndGetAccessToken(String email) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "email": "%s",
                                  "password": "StrongPass123!",
                                  "displayName": "Traveler"
                                }
                                """.formatted(email)))
                .andExpect(status().isCreated())
                .andReturn();
        return json(result).get("accessToken").asText();
    }

    private Message persistentJson(byte[] body) {
        return MessageBuilder.withBody(body)
                .setContentType(MediaType.APPLICATION_JSON_VALUE)
                .setDeliveryMode(MessageDeliveryMode.PERSISTENT)
                .build();
    }

    private void await(Duration timeout, BooleanSupplier condition) throws InterruptedException {
        long deadline = System.nanoTime() + timeout.toNanos();
        while (System.nanoTime() < deadline) {
            if (condition.getAsBoolean()) {
                return;
            }
            Thread.sleep(100);
        }
        throw new AssertionError("Condition was not met within " + timeout);
    }

    private String taskStatus(UUID taskId) {
        return jdbcTemplate.queryForObject(
                "SELECT status FROM business.planning_task WHERE id = ?", String.class, taskId
        );
    }

    private int count(String table) {
        Integer count = jdbcTemplate.queryForObject("SELECT count(*) FROM " + table, Integer.class);
        return count == null ? 0 : count;
    }

    private JsonNode json(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsByteArray());
    }

    private String bearer(String token) {
        return "Bearer " + token;
    }

    private record PlanningContext(UUID tripId, UUID taskId, UUID traceId) {
    }
}
