package io.github.tobehardoo.trippilot.identity;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.support.PostgresIntegrationTest;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.http.HttpHeaders;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.assertj.core.api.Assertions.assertThat;

class AuthenticationFlowIntegrationTest extends PostgresIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    void registersUserWithAnHttpOnlyRefreshCookieAndNoJsonRefreshToken() throws Exception {
        mockMvc.perform(post("/api/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(registerBody("traveler@example.com")))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.user.email").value("traveler@example.com"))
                .andExpect(jsonPath("$.user.displayName").value("Traveler"))
                .andExpect(jsonPath("$.accessToken").isNotEmpty())
                .andExpect(jsonPath("$.refreshToken").doesNotExist())
                .andExpect(header().string(HttpHeaders.SET_COOKIE,
                        org.hamcrest.Matchers.allOf(
                                org.hamcrest.Matchers.containsString("trip_pilot_refresh="),
                                org.hamcrest.Matchers.containsString("Path=/api/auth"),
                                org.hamcrest.Matchers.containsString("Max-Age=2592000"),
                                org.hamcrest.Matchers.containsString("Secure"),
                                org.hamcrest.Matchers.containsString("HttpOnly"),
                                org.hamcrest.Matchers.containsString("SameSite=Strict")
                        )));
    }

    @Test
    void rejectsDuplicateEmail() throws Exception {
        register("duplicate@example.com");

        mockMvc.perform(post("/api/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(registerBody("duplicate@example.com")))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("EMAIL_ALREADY_EXISTS"));
    }

    @Test
    void logsInAndAccessesCurrentUser() throws Exception {
        register("login@example.com");

        MvcResult loginResult = mockMvc.perform(post("/api/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "email": "login@example.com",
                                  "password": "StrongPass123!"
                                }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.accessToken").isNotEmpty())
                .andReturn();

        String accessToken = json(loginResult).get("accessToken").asText();
        mockMvc.perform(get("/api/users/me")
                        .header("Authorization", "Bearer " + accessToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.email").value("login@example.com"));
    }

    @Test
    void rotatesRefreshTokenAndRejectsReuse() throws Exception {
        Cookie originalRefreshCookie = register("refresh@example.com").cookie();

        MvcResult refreshResult = mockMvc.perform(post("/api/auth/refresh")
                        .cookie(originalRefreshCookie))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.refreshToken").doesNotExist())
                .andReturn();

        Cookie rotatedCookie = refreshCookie(refreshResult);
        assertThat(rotatedCookie.getValue()).isNotEqualTo(originalRefreshCookie.getValue());

        mockMvc.perform(post("/api/auth/refresh")
                        .cookie(originalRefreshCookie))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("INVALID_REFRESH_TOKEN"));
    }

    private Registration register(String email) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(registerBody(email)))
                .andExpect(status().isCreated())
                .andReturn();
        return new Registration(json(result), refreshCookie(result));
    }

    private Cookie refreshCookie(MvcResult result) {
        String header = result.getResponse().getHeader(HttpHeaders.SET_COOKIE);
        assertThat(header).isNotBlank();
        String pair = header.split(";", 2)[0];
        return new Cookie("trip_pilot_refresh", pair.substring(pair.indexOf('=') + 1));
    }

    private JsonNode json(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsByteArray());
    }

    private String registerBody(String email) {
        return """
                {
                  "email": "%s",
                  "password": "StrongPass123!",
                  "displayName": "Traveler"
                }
                """.formatted(email);
    }

    private record Registration(JsonNode body, Cookie cookie) {
    }
}
