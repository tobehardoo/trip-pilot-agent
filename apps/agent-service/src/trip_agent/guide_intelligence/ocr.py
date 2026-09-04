"""Content-based image validation and a bounded vision-model OCR adapter.

Images exist only in memory: they are never logged, never persisted, and only
their sha256 hash plus pixel metadata survive into guide provenance.
"""

import asyncio
import base64
import binascii
import hashlib
import io
import os
from typing import Protocol

import httpx
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from trip_agent.providers.settings import structured_model_config

_MAX_IMAGES_DEFAULT = 5
_MAX_IMAGE_BYTES_DEFAULT = 5_000_000
_MAX_TOTAL_BYTES_DEFAULT = 15_000_000
_MIN_DIMENSION_DEFAULT = 64
_MAX_DIMENSION_DEFAULT = 8000

MAX_IMAGES = _MAX_IMAGES_DEFAULT
MAX_IMAGE_BYTES = _MAX_IMAGE_BYTES_DEFAULT
MAX_TOTAL_BYTES = _MAX_TOTAL_BYTES_DEFAULT
MIN_DIMENSION = _MIN_DIMENSION_DEFAULT
MAX_DIMENSION = _MAX_DIMENSION_DEFAULT


def configure_limits_for_tests(
    *,
    max_image_bytes: int | None = None,
    max_total_bytes: int | None = None,
    min_dimension: int | None = None,
    max_dimension: int | None = None,
) -> None:
    global MAX_IMAGES, MAX_IMAGE_BYTES, MAX_TOTAL_BYTES, MIN_DIMENSION, MAX_DIMENSION
    MAX_IMAGES = _MAX_IMAGES_DEFAULT
    MAX_IMAGE_BYTES = max_image_bytes or _MAX_IMAGE_BYTES_DEFAULT
    MAX_TOTAL_BYTES = max_total_bytes or _MAX_TOTAL_BYTES_DEFAULT
    MIN_DIMENSION = min_dimension or _MIN_DIMENSION_DEFAULT
    MAX_DIMENSION = max_dimension or _MAX_DIMENSION_DEFAULT


class ImagePayload(BaseModel):
    """One user-supplied image as base64; mirrors the internal wire contract."""

    model_config = ConfigDict(frozen=True)

    dataBase64: str = Field(min_length=1, max_length=7_500_000)
    filename: str | None = Field(default=None, max_length=255)
    contentType: str | None = Field(default=None, max_length=80)


class OcrError(Exception):
    """User-facing OCR failure carrying a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def detail(self) -> str:
        return f"{self.code}: {self.message}"


class ValidatedImage(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: bytes
    format: str
    media_type: str
    width: int
    height: int
    sha256: str


_MAGIC_SIGNATURES: tuple[tuple[str, bytes], ...] = (
    ("JPEG", b"\xff\xd8\xff"),
    ("PNG", b"\x89PNG\r\n\x1a\n"),
)


def sniff_image_format(data: bytes) -> str | None:
    """Public content-sniffing helper: format from magic bytes, never extension."""
    return _sniff_format(data)


def _sniff_format(data: bytes) -> str | None:
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    for format_name, signature in _MAGIC_SIGNATURES:
        if data.startswith(signature):
            return format_name
    return None


def _media_type(format_name: str) -> str:
    return f"image/{format_name.casefold()}"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_and_validate_images(
    payloads: list[ImagePayload] | None,
) -> tuple[ValidatedImage, ...]:
    if not payloads:
        raise OcrError("IMAGE_REQUIRED", "请至少选择一张攻略截图。")
    if len(payloads) > MAX_IMAGES:
        raise OcrError(
            "IMAGE_TOO_MANY",
            f"一次最多导入 {MAX_IMAGES} 张图片，请分批或精选关键截图。",
        )
    validated: list[ValidatedImage] = []
    total_bytes = 0
    for index, payload in enumerate(payloads, start=1):
        try:
            data = base64.b64decode(payload.dataBase64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise OcrError(
                "IMAGE_INVALID",
                f"第 {index} 张图片不是有效的图片文件，仅支持 PNG、JPEG 或 WEBP。",
            ) from error
        if not data:
            raise OcrError(
                "IMAGE_INVALID",
                f"第 {index} 张图片内容为空，请重新选择截图。",
            )
        if len(data) > MAX_IMAGE_BYTES:
            raise OcrError(
                "IMAGE_TOO_LARGE",
                f"第 {index} 张图片超过 {MAX_IMAGE_BYTES // 1_000_000} MB 上限，请压缩后重试。",
            )
        total_bytes += len(data)
        if total_bytes > MAX_TOTAL_BYTES:
            raise OcrError(
                "IMAGE_TOTAL_TOO_LARGE",
                f"图片总大小不能超过 {MAX_TOTAL_BYTES // 1_000_000} MB，请减少数量或压缩截图。",
            )
        sniffed = _sniff_format(data)
        if sniffed is None:
            raise OcrError(
                "IMAGE_INVALID",
                f"第 {index} 张图片格式不受支持，仅支持 PNG、JPEG 或 WEBP。",
            )
        try:
            with Image.open(io.BytesIO(data)) as probe:
                probe.verify()
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                actual_format = image.format or sniffed
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise OcrError(
                "IMAGE_INVALID",
                f"第 {index} 张图片已损坏或无法解析，请更换截图后重试。",
            ) from error
        if actual_format != sniffed:
            actual_format = sniffed
        if not (MIN_DIMENSION <= width <= MAX_DIMENSION) or not (
            MIN_DIMENSION <= height <= MAX_DIMENSION
        ):
            raise OcrError(
                "IMAGE_DIMENSIONS_INVALID",
                "图片尺寸需在 "
                f"{MIN_DIMENSION}x{MIN_DIMENSION} 到 {MAX_DIMENSION}x{MAX_DIMENSION} 像素之间。",
            )
        validated.append(
            ValidatedImage(
                data=data,
                format=actual_format,
                media_type=_media_type(actual_format),
                width=width,
                height=height,
                sha256=_sha256_hex(data),
            )
        )
    return tuple(validated)


class OcrTransport(Protocol):
    async def recognize(
        self,
        *,
        image_data_url: str,
        timeout_seconds: float,
    ) -> object: ...


_OCR_PROMPT = (
    "识别图片中的全部文字，按原始阅读顺序输出；"
    "不要翻译、不要解释、不要添加图片中不存在的内容。"
)


def _image_data_url(image: ValidatedImage) -> str:
    encoded = base64.b64encode(image.data).decode("ascii")
    return f"data:{image.media_type};base64,{encoded}"


class HttpVisionOcrProvider:
    """Call an OpenAI-compatible vision chat endpoint without logging images."""

    def __init__(
        self,
        *,
        transport: OcrTransport,
        timeout_seconds: float = 15.0,
        max_retries: int = 0,
    ) -> None:
        if not 0 < timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be between zero and 60")
        if not 0 <= max_retries <= 3:
            raise ValueError("max_retries must be between zero and three")
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    async def recognize(self, image: ValidatedImage) -> str:
        data_url = _image_data_url(image)
        last_error: Exception | None = None
        for _attempt in range(1, self._max_retries + 2):
            try:
                raw_result = await self._transport.recognize(
                    image_data_url=data_url,
                    timeout_seconds=self._timeout_seconds,
                )
                return _parse_text(raw_result)
            except TimeoutError as error:
                last_error = error
            except httpx.TimeoutException as error:
                last_error = error
            except (KeyError, IndexError, TypeError, ValueError) as error:
                raise OcrError(
                    "OCR_FAILED",
                    "图片识别服务返回异常，请稍后重试或改用粘贴正文导入。",
                ) from error
            except httpx.HTTPError as error:
                last_error = error
        if isinstance(last_error, TimeoutError | httpx.TimeoutException):
            raise OcrError(
                "OCR_TIMEOUT",
                "图片识别超时，请减少图片数量后重试，或改用粘贴正文导入。",
            ) from last_error
        raise OcrError(
            "OCR_FAILED",
            "图片识别服务暂时不可用，请稍后重试或改用粘贴正文导入。",
        ) from last_error


def _parse_text(raw_result: object) -> str:
    if not isinstance(raw_result, dict):
        raise ValueError("vision response must be an object")
    choices = raw_result["choices"]
    message = choices[0]["message"]
    content = message["content"]
    if not isinstance(content, str):
        raise ValueError("vision response content must be text")
    return content.strip()


class HttpVisionOcrTransport:
    """POST one image to an OpenAI-compatible vision endpoint."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        http_client: httpx.AsyncClient,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("OCR model endpoint must use HTTPS")
        if not api_key.strip() or not model.strip():
            raise ValueError("OCR model API key and model are required")
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._http_client = http_client

    async def recognize(
        self,
        *,
        image_data_url: str,
        timeout_seconds: float,
    ) -> object:
        response = await self._http_client.post(
            self._endpoint,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _OCR_PROMPT},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    }
                ],
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        return response.json()


def configured_ocr_provider(
    http_client: httpx.AsyncClient,
) -> HttpVisionOcrProvider | None:
    endpoint = os.getenv("OCR_MODEL_ENDPOINT", "").strip()
    api_key = os.getenv("OCR_MODEL_API_KEY", "").strip()
    model = os.getenv("OCR_MODEL_NAME", "").strip()
    if not endpoint or not api_key or not model:
        return None
    return HttpVisionOcrProvider(
        transport=HttpVisionOcrTransport(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            http_client=http_client,
        ),
        timeout_seconds=float(os.getenv("OCR_MODEL_TIMEOUT_SECONDS", "15")),
        max_retries=int(os.getenv("OCR_MODEL_MAX_RETRIES", "0")),
    )


class ScanTextExtractor(Protocol):
    """Local fallback that scans an image for text without a vision model."""

    async def extract_text(self, image: ValidatedImage) -> str: ...


class RapidScanTextExtractor:
    """RapidOCR-based scan fallback; models load lazily and run in a thread."""

    def __init__(self) -> None:
        self._engine: object | None = None

    async def extract_text(self, image: ValidatedImage) -> str:
        engine = await asyncio.to_thread(self._ensure_engine)

        def run_scan() -> list[str]:
            import numpy as np
            from PIL import Image

            with Image.open(io.BytesIO(image.data)) as decoded:
                pixels = np.asarray(decoded.convert("RGB"))
            result = engine(pixels)
            # RapidOCR 1.4.4 returns (detections, elapsed); rails on older
            # lists must both be handled so we only read real text entries.
            detections = result[0] if isinstance(result, tuple) else result
            lines: list[str] = []
            for item in detections or []:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                text = str(item[1]).strip()
                if text:
                    lines.append(text)
            return lines

        lines = await asyncio.to_thread(run_scan)
        if not lines:
            raise OcrError(
                "OCR_NO_TEXT",
                "本地扫描未从图片中提取到文字，请确认截图清晰并包含攻略正文。",
            )
        return "\n".join(lines)

    def _ensure_engine(self) -> object:
        if self._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as error:
                raise OcrError(
                    "OCR_SCAN_UNAVAILABLE",
                    "本地扫描组件未安装：请安装可选依赖 "
                    "'pip install \"trip-agent[ocr-scan]\"' 后重试。",
                ) from error
            self._engine = RapidOCR()
        return self._engine


def scan_fallback_enabled() -> bool:
    return os.getenv("OCR_FALLBACK_SCAN_ENABLED", "true").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def configured_scan_extractor() -> RapidScanTextExtractor | None:
    if not scan_fallback_enabled():
        return None
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        return None
    return RapidScanTextExtractor()


class TextRefiner(Protocol):
    """Optional LLM cleanup for raw scan text."""

    async def refine(self, raw_text: str) -> str: ...


class HttpTextRefiner:
    """Plain OpenAI-compatible completion that tidies scanned text only."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        http_client: httpx.AsyncClient,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("text refiner endpoint must use HTTPS")
        if not api_key.strip() or not model.strip():
            raise ValueError("text refiner API key and model are required")
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._http_client = http_client

    async def refine(self, raw_text: str) -> str:
        response = await self._http_client.post(
            self._endpoint,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是文字整理助手。仅根据给定扫描文字整理为通顺的中文旅行攻略文本；"
                            "保留全部事实（地点、地址、价格、时间、预约要求、交通提示），"
                            "不翻译、不添加不存在的信息、不输出解释。"
                        ),
                    },
                    {"role": "user", "content": raw_text[:20_000]},
                ],
            },
            timeout=8.0,
        )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("text refiner response content must be text")
        return content.strip()


def configured_text_refiner(
    http_client: httpx.AsyncClient,
) -> HttpTextRefiner | None:
    """Reuse the structured-model credentials for scan-text cleanup."""
    shared = structured_model_config()
    if shared is None:
        return None
    return HttpTextRefiner(
        endpoint=shared.endpoint,
        api_key=shared.api_key,
        model=shared.model,
        http_client=http_client,
    )
