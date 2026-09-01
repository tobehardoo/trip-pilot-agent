package io.github.tobehardoo.trippilot.identity;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.security.SecurityProperties;
import jakarta.validation.Valid;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;
    private final SecurityProperties securityProperties;

    public AuthController(AuthService authService, SecurityProperties securityProperties) {
        this.authService = authService;
        this.securityProperties = securityProperties;
    }

    @PostMapping("/register")
    ResponseEntity<AuthService.AuthResponse> register(@Valid @RequestBody RegisterRequest request) {
        return authenticated(authService.register(request), HttpStatus.CREATED);
    }

    @PostMapping("/login")
    ResponseEntity<AuthService.AuthResponse> login(@Valid @RequestBody LoginRequest request) {
        return authenticated(authService.login(request), HttpStatus.OK);
    }

    @PostMapping("/refresh")
    ResponseEntity<AuthService.AuthResponse> refresh(
            @CookieValue(name = "trip_pilot_refresh", required = false) String refreshToken) {
        return authenticated(
                authService.refresh(requireRefreshToken(refreshToken)),
                HttpStatus.OK
        );
    }

    @PostMapping("/logout")
    ResponseEntity<Void> logout(
            @CookieValue(name = "trip_pilot_refresh", required = false) String refreshToken) {
        if (refreshToken != null && !refreshToken.isBlank()) {
            authService.logout(refreshToken);
        }
        return ResponseEntity.noContent()
                .header(HttpHeaders.SET_COOKIE, refreshCookie("", 0).toString())
                .build();
    }

    private ResponseEntity<AuthService.AuthResponse> authenticated(
            AuthService.AuthResponse response,
            HttpStatus status) {
        return ResponseEntity.status(status)
                .header(HttpHeaders.SET_COOKIE, refreshCookie(
                        response.refreshToken(),
                        securityProperties.refreshTokenTtl().toSeconds()
                ).toString())
                .body(response);
    }

    private ResponseCookie refreshCookie(String value, long maxAgeSeconds) {
        return ResponseCookie.from("trip_pilot_refresh", value)
                .httpOnly(true)
                .secure(securityProperties.refreshCookieSecure())
                .sameSite("Strict")
                .path("/api/auth")
                .maxAge(maxAgeSeconds)
                .build();
    }

    private String requireRefreshToken(String refreshToken) {
        if (refreshToken == null || refreshToken.isBlank()) {
            throw new ApiException(
                    HttpStatus.UNAUTHORIZED,
                    "INVALID_REFRESH_TOKEN",
                    "Refresh token is invalid or expired"
            );
        }
        return refreshToken;
    }
}
