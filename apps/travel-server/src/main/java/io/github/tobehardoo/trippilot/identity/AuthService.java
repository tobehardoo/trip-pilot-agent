package io.github.tobehardoo.trippilot.identity;

import java.time.Clock;
import java.time.Instant;
import java.util.Locale;
import java.util.UUID;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.security.SecurityProperties;
import io.github.tobehardoo.trippilot.security.TokenService;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuthService {

    private final UserAccountMapper userMapper;
    private final RefreshTokenMapper refreshTokenMapper;
    private final PasswordEncoder passwordEncoder;
    private final TokenService tokenService;
    private final SecurityProperties securityProperties;
    private final Clock clock = Clock.systemUTC();

    public AuthService(UserAccountMapper userMapper, RefreshTokenMapper refreshTokenMapper,
                       PasswordEncoder passwordEncoder, TokenService tokenService,
                       SecurityProperties securityProperties) {
        this.userMapper = userMapper;
        this.refreshTokenMapper = refreshTokenMapper;
        this.passwordEncoder = passwordEncoder;
        this.tokenService = tokenService;
        this.securityProperties = securityProperties;
    }

    @Transactional
    public AuthResponse register(RegisterRequest request) {
        UserAccount user = new UserAccount(
                UUID.randomUUID(),
                normalizeEmail(request.email()),
                passwordEncoder.encode(request.password()),
                request.displayName().trim(),
                null
        );
        try {
            userMapper.insert(user);
        } catch (DuplicateKeyException exception) {
            throw new ApiException(HttpStatus.CONFLICT, "EMAIL_ALREADY_EXISTS", "Email is already registered");
        }
        return issueTokenPair(user);
    }

    @Transactional
    public AuthResponse login(LoginRequest request) {
        UserAccount user = userMapper.findByEmail(normalizeEmail(request.email()))
                .orElseThrow(this::invalidCredentials);
        if (!passwordEncoder.matches(request.password(), user.passwordHash())) {
            throw invalidCredentials();
        }
        return issueTokenPair(user);
    }

    @Transactional
    public AuthResponse refresh(RefreshRequest request) {
        Instant now = clock.instant();
        RefreshTokenRecord existing = refreshTokenMapper
                .findByHashForUpdate(tokenService.hashRefreshToken(request.refreshToken()))
                .filter(token -> token.revokedAt() == null && token.expiresAt().isAfter(now))
                .orElseThrow(this::invalidRefreshToken);
        UserAccount user = userMapper.findById(existing.userId()).orElseThrow(this::invalidRefreshToken);

        String rawReplacement = tokenService.createRefreshToken();
        RefreshTokenRecord replacement = new RefreshTokenRecord(
                UUID.randomUUID(), user.id(), tokenService.hashRefreshToken(rawReplacement),
                now.plus(securityProperties.refreshTokenTtl()), null
        );
        refreshTokenMapper.insert(replacement);
        if (refreshTokenMapper.revoke(existing.id(), now, replacement.id()) != 1) {
            throw invalidRefreshToken();
        }
        return response(user, tokenService.createAccessToken(user), rawReplacement);
    }

    @Transactional
    public void logout(RefreshRequest request) {
        Instant now = clock.instant();
        refreshTokenMapper.findByHashForUpdate(tokenService.hashRefreshToken(request.refreshToken()))
                .filter(token -> token.revokedAt() == null)
                .ifPresent(token -> refreshTokenMapper.revoke(token.id(), now, null));
    }

    public UserResponse currentUser(UUID userId) {
        return userMapper.findById(userId)
                .map(this::toUserResponse)
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "UNAUTHORIZED", "User is unavailable"));
    }

    private AuthResponse issueTokenPair(UserAccount user) {
        String rawRefreshToken = tokenService.createRefreshToken();
        refreshTokenMapper.insert(new RefreshTokenRecord(
                UUID.randomUUID(), user.id(), tokenService.hashRefreshToken(rawRefreshToken),
                clock.instant().plus(securityProperties.refreshTokenTtl()), null
        ));
        return response(user, tokenService.createAccessToken(user), rawRefreshToken);
    }

    private AuthResponse response(UserAccount user, String accessToken, String refreshToken) {
        return new AuthResponse(toUserResponse(user), accessToken, refreshToken, "Bearer",
                securityProperties.accessTokenTtl().toSeconds());
    }

    private UserResponse toUserResponse(UserAccount user) {
        return new UserResponse(user.id(), user.email(), user.displayName());
    }

    private String normalizeEmail(String email) {
        return email.trim().toLowerCase(Locale.ROOT);
    }

    private ApiException invalidCredentials() {
        return new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_CREDENTIALS", "Email or password is incorrect");
    }

    private ApiException invalidRefreshToken() {
        return new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_REFRESH_TOKEN", "Refresh token is invalid or expired");
    }

    public record AuthResponse(UserResponse user, String accessToken, String refreshToken,
                               String tokenType, long expiresIn) {
    }

    public record UserResponse(UUID id, String email, String displayName) {
    }
}
