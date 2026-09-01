package io.github.tobehardoo.trippilot.identity;

import jakarta.validation.constraints.NotBlank;

/**
 * The login identifier is not forced to be an email: the seeded admin account
 * authenticates with the plain username "admin".
 */
public record LoginRequest(@NotBlank String email, @NotBlank String password) {
}
