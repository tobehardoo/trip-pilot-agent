package io.github.tobehardoo.trippilot.identity;

import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import com.fasterxml.jackson.databind.JsonNode;
import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.http.HttpHeaders;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class AuthenticationSecurityIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void storesNormalizedEmailAndBcryptPasswordHash() throws Exception {
        register("Secure.User@Example.COM");

        String storedEmail = jdbcTemplate.queryForObject(
                "SELECT email FROM business.user_account", String.class);
        String storedHash = jdbcTemplate.queryForObject(
                "SELECT password_hash FROM business.user_account", String.class);

        assertThat(storedEmail).isEqualTo("secure.user@example.com");
        assertThat(storedHash).startsWith("$2").doesNotContain("StrongPass123!");
    }

    @Test
    void rejectsWrongPasswordWithoutDisclosingAccountState() throws Exception {
        register("known@example.com");

        mockMvc.perform(post("/api/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"known@example.com","password":"WrongPassword123!"}
                                """))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("INVALID_CREDENTIALS"));

        mockMvc.perform(post("/api/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"missing@example.com","password":"WrongPassword123!"}
                                """))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("INVALID_CREDENTIALS"));
    }

    @Test
    void rejectsMalformedRegistrationAndUnknownRefreshToken() throws Exception {
        mockMvc.perform(post("/api/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"not-an-email","password":"short","displayName":""}
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
                .andExpect(jsonPath("$.violations.length()").value(3));

        mockMvc.perform(post("/api/auth/refresh")
                        .cookie(new Cookie("trip_pilot_refresh", "unknown-token")))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("INVALID_REFRESH_TOKEN"));
    }

    @Test
    void rejectsExpiredRefreshToken() throws Exception {
        Cookie refreshCookie = register("expired@example.com");
        jdbcTemplate.update("UPDATE business.refresh_token SET expires_at = CURRENT_TIMESTAMP - INTERVAL '1 second'");

        mockMvc.perform(post("/api/auth/refresh")
                        .cookie(refreshCookie))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("INVALID_REFRESH_TOKEN"));
    }

    @Test
    void logoutRevokesRefreshToken() throws Exception {
        Cookie refreshCookie = register("logout@example.com");

        mockMvc.perform(post("/api/auth/logout")
                        .cookie(refreshCookie))
                .andExpect(status().isNoContent())
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.header()
                        .string(HttpHeaders.SET_COOKIE, org.hamcrest.Matchers.containsString("Max-Age=0")));

        mockMvc.perform(post("/api/auth/refresh")
                        .cookie(refreshCookie))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("INVALID_REFRESH_TOKEN"));
    }

    @Test
    void allowsOnlyOneConcurrentRefreshForTheSameToken() throws Exception {
        Cookie refreshCookie = register("concurrent@example.com");
        CountDownLatch start = new CountDownLatch(1);

        try (ExecutorService executor = Executors.newFixedThreadPool(2)) {
            Future<Integer> first = executor.submit(() -> refreshStatusAfter(start, refreshCookie));
            Future<Integer> second = executor.submit(() -> refreshStatusAfter(start, refreshCookie));
            start.countDown();

            assertThat(List.of(first.get(), second.get())).containsExactlyInAnyOrder(200, 401);
        }
    }

    private int refreshStatusAfter(CountDownLatch start, Cookie refreshCookie) throws Exception {
        start.await();
        return mockMvc.perform(post("/api/auth/refresh")
                        .cookie(refreshCookie))
                .andReturn()
                .getResponse()
                .getStatus();
    }

    private Cookie register(String email) throws Exception {
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
        String header = result.getResponse().getHeader(HttpHeaders.SET_COOKIE);
        assertThat(header).isNotBlank();
        String pair = header.split(";", 2)[0];
        return new Cookie("trip_pilot_refresh", pair.substring(pair.indexOf('=') + 1));
    }
}
