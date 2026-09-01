package io.github.tobehardoo.trippilot.guide;

import static org.assertj.core.api.Assertions.assertThat;

import io.github.tobehardoo.trippilot.common.ApiException;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

/**
 * The agent-service reports OCR failures as 422 with a stable "CODE: message"
 * detail prefix; the Java client must surface them as distinct user-facing
 * error codes instead of the generic guide rejection.
 */
class GuideIntelligenceErrorMappingTest {

    private static ApiException map(String detail) {
        return HttpGuideIntelligenceClient.rejectionFor(
                "{\"detail\":\"" + detail + "\"}"
        );
    }

    @Test
    void ocrNotConfiguredMapsToDedicatedErrorCode() {
        ApiException exception = map("OCR_NOT_CONFIGURED: 图片识别未配置。");

        assertThat(exception.code()).isEqualTo("GUIDE_OCR_NOT_CONFIGURED");
        assertThat(exception.status()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);
    }

    @Test
    void ocrTimeoutMapsToDedicatedErrorCode() {
        assertThat(map("OCR_TIMEOUT: 图片识别超时").code()).isEqualTo("GUIDE_OCR_TIMEOUT");
    }

    @Test
    void unusableOcrTextMapsToFailingCode() {
        assertThat(map("OCR_NO_TEXT: 没有文字").code()).isEqualTo("GUIDE_OCR_FAILED");
        assertThat(map("OCR_TEXT_TOO_SHORT: 文字太少").code()).isEqualTo("GUIDE_OCR_FAILED");
        assertThat(map("OCR_FAILED: 服务异常").code()).isEqualTo("GUIDE_OCR_FAILED");
    }

    @Test
    void invalidImagesMapToImageSpecificCode() {
        ApiException exception = map("IMAGE_INVALID: 第 1 张图片格式不受支持");

        assertThat(exception.code()).isEqualTo("GUIDE_IMAGE_INVALID");
    }

    @Test
    void unknownRejectionsKeepTheGenericGuideCode() {
        assertThat(map("some other validation failure").code())
                .isEqualTo("GUIDE_IMPORT_REJECTED");
        assertThat(HttpGuideIntelligenceClient.rejectionFor(null).code())
                .isEqualTo("GUIDE_IMPORT_REJECTED");
    }
}
