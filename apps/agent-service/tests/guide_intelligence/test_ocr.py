"""Tests for image decoding/validation and the vision OCR adapter."""

import asyncio
import base64
import io
import logging

import httpx
import pytest
from PIL import Image

from trip_agent.guide_intelligence import ocr as ocr_module
from trip_agent.guide_intelligence.ocr import (
    HttpVisionOcrProvider,
    ImagePayload,
    OcrError,
    configure_limits_for_tests,
    configured_ocr_provider,
    decode_and_validate_images,
)


def _png_bytes(width: int = 96, height: int = 96) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(200, 120, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_bytes(width: int = 96, height: int = 96) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(20, 120, 240)).save(
        buffer, format="JPEG", quality=85
    )
    return buffer.getvalue()


def _webp_bytes(width: int = 96, height: int = 96) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(90, 200, 60)).save(
        buffer, format="WEBP", quality=85
    )
    return buffer.getvalue()


def _payload(data: bytes, filename: str | None = None, content_type: str | None = None):
    return ImagePayload(
        dataBase64=base64.b64encode(data).decode("ascii"),
        filename=filename,
        contentType=content_type,
    )


@pytest.fixture(autouse=True)
def _fast_limits(monkeypatch):
    configure_limits_for_tests(
        max_image_bytes=200_000,
        max_total_bytes=400_000,
        min_dimension=64,
        max_dimension=600,
    )
    yield
    configure_limits_for_tests()


def test_rejects_empty_image_list():
    with pytest.raises(OcrError) as excinfo:
        decode_and_validate_images([])
    assert excinfo.value.code == "IMAGE_REQUIRED"


def test_rejects_more_than_max_images(monkeypatch):
    monkeypatch.setattr(ocr_module, "MAX_IMAGES", 2)
    payloads = [_payload(_png_bytes()) for _ in range(3)]
    with pytest.raises(OcrError) as excinfo:
        decode_and_validate_images(payloads)
    assert excinfo.value.code == "IMAGE_TOO_MANY"


def test_rejects_invalid_base64():
    with pytest.raises(OcrError) as excinfo:
        decode_and_validate_images([ImagePayload(dataBase64="not-base64!!!")])
    assert excinfo.value.code == "IMAGE_INVALID"


def test_reports_actual_format_not_declared_mime():
    validated = decode_and_validate_images(
        [
            _payload(_jpeg_bytes(), filename="looks-png.png", content_type="image/png"),
            _payload(_webp_bytes(), filename="b.webp", content_type="image/webp"),
        ]
    )
    assert [image.format for image in validated] == ["JPEG", "WEBP"]
    assert validated[0].media_type == "image/jpeg"
    assert validated[0].width == 96
    assert validated[0].height == 96
    assert len(validated[0].sha256) == 64


def test_rejects_non_supported_magic_bytes_even_when_mime_claims_png():
    gif = b"GIF89a" + b"\x00" * 128
    with pytest.raises(OcrError) as excinfo:
        decode_and_validate_images([_payload(gif, content_type="image/png")])
    assert excinfo.value.code == "IMAGE_INVALID"


def test_rejects_oversized_single_image(monkeypatch):
    monkeypatch.setattr(ocr_module, "MAX_IMAGE_BYTES", 64)
    with pytest.raises(OcrError) as excinfo:
        decode_and_validate_images([_payload(_png_bytes())])
    assert excinfo.value.code == "IMAGE_TOO_LARGE"


def test_enforces_total_size_budget_across_images(monkeypatch):
    monkeypatch.setattr(ocr_module, "MAX_TOTAL_BYTES", 100)
    with pytest.raises(OcrError) as excinfo:
        decode_and_validate_images(
            [_payload(_png_bytes()), _payload(_png_bytes())]
        )
    assert excinfo.value.code == "IMAGE_TOTAL_TOO_LARGE"


def test_rejects_dimensions_below_minimum():
    with pytest.raises(OcrError) as excinfo:
        decode_and_validate_images([_payload(_png_bytes(width=32, height=32))])
    assert excinfo.value.code == "IMAGE_DIMENSIONS_INVALID"


def test_rejects_dimensions_above_maximum():
    with pytest.raises(OcrError) as excinfo:
        decode_and_validate_images([_payload(_png_bytes(width=700, height=700))])
    assert excinfo.value.code == "IMAGE_DIMENSIONS_INVALID"


def test_corrupt_but_magic_prefixed_image_fails_closed():
    corrupt = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    with pytest.raises(OcrError) as excinfo:
        decode_and_validate_images([_payload(corrupt)])
    assert excinfo.value.code == "IMAGE_INVALID"


class StubTransport:
    def __init__(self, outcome: object | Exception):
        self._outcome = outcome
        self.calls: list[str] = []

    async def recognize(
        self,
        *,
        image_data_url: str,
        timeout_seconds: float,
    ) -> object:
        self.calls.append(image_data_url)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


async def _recognize_with(provider: HttpVisionOcrProvider, png: bytes | None = None):
    (validated,) = decode_and_validate_images([_payload(png or _png_bytes())])
    return await provider.recognize(validated)


def test_provider_returns_model_text_on_success():
    transport = StubTransport(
        {"choices": [{"message": {"content": "陈家祠地址：中山七路。"}}]}
    )
    provider = HttpVisionOcrProvider(transport=transport)
    text = asyncio.run(_recognize_with(provider))
    assert text == "陈家祠地址：中山七路。"
    assert transport.calls[0].startswith("data:image/png;base64,")


def test_provider_timeout_maps_to_ocr_timeout():
    transport = StubTransport(httpx.TimeoutException("timed out"))
    provider = HttpVisionOcrProvider(transport=transport, max_retries=0)
    with pytest.raises(OcrError) as excinfo:
        asyncio.run(_recognize_with(provider))
    assert excinfo.value.code == "OCR_TIMEOUT"


def test_provider_http_error_maps_to_ocr_failed():
    transport = StubTransport(httpx.ConnectError("refused"))
    provider = HttpVisionOcrProvider(transport=transport)
    with pytest.raises(OcrError) as excinfo:
        asyncio.run(_recognize_with(provider))
    assert excinfo.value.code == "OCR_FAILED"


def test_provider_malformed_response_maps_to_ocr_failed():
    transport = StubTransport({"unexpected": "shape"})
    provider = HttpVisionOcrProvider(transport=transport)
    with pytest.raises(OcrError) as excinfo:
        asyncio.run(_recognize_with(provider))
    assert excinfo.value.code == "OCR_FAILED"


def test_provider_never_logs_image_or_prompt_payload(caplog):
    transport = StubTransport(httpx.ConnectError("refused"))
    provider = HttpVisionOcrProvider(transport=transport)
    (validated,) = decode_and_validate_images([_payload(_png_bytes())])
    image_base64 = base64.b64encode(validated.data).decode("ascii")
    with caplog.at_level(logging.DEBUG), pytest.raises(OcrError):
        asyncio.run(provider.recognize(validated))
    assert image_base64 not in caplog.text
    assert "data:image" not in caplog.text


def test_configured_ocr_provider_requires_full_configuration(monkeypatch):
    monkeypatch.delenv("OCR_MODEL_ENDPOINT", raising=False)
    monkeypatch.delenv("OCR_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OCR_MODEL_NAME", raising=False)

    assert configured_ocr_provider(httpx.AsyncClient(trust_env=False)) is None

    monkeypatch.setenv("OCR_MODEL_ENDPOINT", "https://ocr.example.com/v1/chat/completions")
    monkeypatch.setenv("OCR_MODEL_API_KEY", "secret-key")
    monkeypatch.setenv("OCR_MODEL_NAME", "qwen-vl-max")
    provider = configured_ocr_provider(httpx.AsyncClient(trust_env=False))
    assert isinstance(provider, HttpVisionOcrProvider)
