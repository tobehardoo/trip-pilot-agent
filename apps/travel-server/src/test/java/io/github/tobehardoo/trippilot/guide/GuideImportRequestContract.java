package io.github.tobehardoo.trippilot.guide;

import java.util.List;

/**
 * Contract expectations shared by the guide import API surface: which source
 * channels exist and how each channel's payload must be shaped.
 */
class GuideImportRequestContract {

    static final String IMAGE_BASE64_ONE_BY_ONE_PNG =
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
                    + "h6FO1AAAAABJRU5ErkJggg==";

    static GuideImportRequest imageOcrRequest() {
        return new GuideImportRequest(
                null,
                "IMAGE_OCR",
                null,
                null,
                null,
                null,
                null,
                List.of(new GuideImagePayload(IMAGE_BASE64_ONE_BY_ONE_PNG, "guide.png", "image/png"))
        );
    }
}
