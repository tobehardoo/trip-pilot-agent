package io.github.tobehardoo.trippilot.guide;

import jakarta.validation.constraints.Size;

/**
 * One user-supplied image as base64. Raw bytes never leave this field: they
 * are forwarded to the agent-service for OCR and are not logged or persisted.
 */
public record GuideImagePayload(
        @Size(
                max = 7_500_000,
                message = "each image must stay below 5 MB after base64 encoding"
        )
        String dataBase64,
        @Size(max = 255) String fileName,
        @Size(max = 80) String contentType
) {
}
