from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from trip_agent.guide_intelligence.models import GuideImportResult, TravelFact
from trip_agent.guide_intelligence.ocr import ImagePayload, OcrError
from trip_agent.main import app


class StubImportService:
    async def import_url(self, source_url: str) -> GuideImportResult:
        fetched_at = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
        return GuideImportResult(
            source_type="PUBLIC_GUIDE_URL",
            source_url=source_url,
            final_url=source_url,
            source_host="example.com",
            title="Public guide",
            excerpt="Take metro line 2.",
            content_hash="a" * 64,
            fetched_at=fetched_at,
            facts=(
                TravelFact(
                    category="TRANSPORT",
                    statement="Take metro line 2.",
                    evidence="Take metro line 2.",
                    confidence=0.84,
                    observed_at=fetched_at,
                    expires_at=fetched_at + timedelta(days=14),
                ),
            ),
        )

    async def import_text_with_model(
        self,
        *,
        source_type: str,
        title: str,
        content: str,
        observed_at: datetime | None = None,
    ) -> GuideImportResult:
        fetched_at = datetime(2026, 7, 26, 8, 0, tzinfo=UTC)
        return GuideImportResult(
            source_type=source_type,
            source_url="https://user-content.trippilot.invalid/import/test",
            final_url="https://user-content.trippilot.invalid/import/test",
            source_host="用户粘贴文本",
            title=title,
            excerpt=content,
            content_hash="b" * 64,
            fetched_at=fetched_at,
            facts=(),
        )

    async def import_city(
        self,
        *,
        city: str,
        start_date: date,
        end_date: date,
    ) -> GuideImportResult:
        fetched_at = datetime(2026, 7, 26, 8, 0, tzinfo=UTC)
        return GuideImportResult(
            source_type="CITY_INTELLIGENCE",
            source_url="https://lbs.amap.com/api/webservice/guide/api/weatherinfo",
            final_url="https://lbs.amap.com/api/webservice/guide/api/weatherinfo",
            source_host="高德城市情报",
            title=f"{city}城市实时情报",
            excerpt=f"{start_date} 至 {end_date} 天气预报",
            content_hash="c" * 64,
            fetched_at=fetched_at,
            facts=(),
        )

    async def import_registered_source(
        self,
        *,
        source_url: str,
        source_name: str,
        source_type: str,
        city: str,
    ) -> GuideImportResult:
        fetched_at = datetime(2026, 7, 26, 8, 0, tzinfo=UTC)
        return GuideImportResult(
            source_type=source_type,
            source_url=source_url,
            final_url=source_url,
            source_host="museum.example",
            title=source_name,
            excerpt=f"{city}官方参观须知",
            content_hash="d" * 64,
            fetched_at=fetched_at,
            facts=(),
        )

    async def import_images(
        self,
        *,
        images: list[ImagePayload] | None,
    ) -> GuideImportResult:
        fetched_at = datetime(2026, 7, 26, 8, 0, tzinfo=UTC)
        if images is None:
            raise ValueError("image imports require only base64 image payloads")
        return GuideImportResult(
            source_type="IMAGE_OCR",
            source_url="https://user-content.trippilot.invalid/image-ocr/test",
            final_url="https://user-content.trippilot.invalid/image-ocr/test",
            source_host="用户图片截图",
            title="图片攻略",
            excerpt="识别文本",
            content_hash="e" * 64,
            fetched_at=fetched_at,
            facts=(),
        )


def test_internal_token_is_required(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")

    response = TestClient(app).post(
        "/internal/v1/guide-imports",
        json={"sourceUrl": "https://example.com/guide"},
    )

    assert response.status_code == 401


def test_returns_camel_case_traceable_guide_contract(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setattr(
        "trip_agent.guide_intelligence.api.GuideImportService",
        StubImportService,
    )

    response = TestClient(app).post(
        "/internal/v1/guide-imports",
        headers={"X-Internal-Token": "test-internal-token"},
        json={"sourceUrl": "https://example.com/guide"},
    )

    assert response.status_code == 200
    assert response.json()["sourceHost"] == "example.com"
    assert response.json()["facts"][0]["category"] == "TRANSPORT"
    assert response.json()["facts"][0]["expiresAt"] == "2026-08-06T08:00:00Z"


def test_accepts_user_provided_text_without_fetching_a_url(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setattr(
        "trip_agent.guide_intelligence.api.GuideImportService",
        StubImportService,
    )

    response = TestClient(app).post(
        "/internal/v1/guide-imports",
        headers={"X-Internal-Token": "test-internal-token"},
        json={
            "sourceType": "TEXT_FILE",
            "title": "广州攻略.txt",
            "content": "陈家祠地址是中山七路，门票10元。",
        },
    )

    assert response.status_code == 200
    assert response.json()["sourceType"] == "TEXT_FILE"
    assert response.json()["sourceHost"] == "用户粘贴文本"


def test_text_import_returns_v13_trusted_fact_contract(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.delenv("STRUCTURED_MODEL_ENDPOINT", raising=False)
    monkeypatch.delenv("STRUCTURED_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("STRUCTURED_MODEL_NAME", raising=False)

    response = TestClient(app).post(
        "/internal/v1/guide-imports",
        headers={"X-Internal-Token": "test-internal-token"},
        json={
            "sourceType": "TEXT_FILE",
            "title": "广州攻略.txt",
            "content": (
                "陈家祠地址：广州市荔湾区中山七路恩龙里34号。\n"
                "开放时间：09:00-17:30，成人门票10元，需要提前预约。"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["normalizedDocument"]["sourceType"] == "TEXT_FILE"
    assert body["normalizedDocument"]["encoding"] == "utf-8"
    assert {fact["category"] for fact in body["trustedFacts"]} >= {
        "ADDRESS",
        "OPENING_HOURS",
        "TICKET_PRICE",
        "RESERVATION_REQUIREMENT",
    }
    assert all(
        fact["evidence"]
        == body["normalizedDocument"]["content"][
            fact["evidenceStart"] : fact["evidenceEnd"]
        ]
        for fact in body["trustedFacts"]
    )
    assert body["modelExtraction"]["status"] == "SKIPPED"
    assert body["modelExtraction"]["failureCode"] == "MODEL_NOT_CONFIGURED"


def test_rejects_ambiguous_guide_import_input(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")

    response = TestClient(app).post(
        "/internal/v1/guide-imports",
        headers={"X-Internal-Token": "test-internal-token"},
        json={
            "sourceUrl": "https://example.com/guide",
            "sourceType": "PASTED_TEXT",
            "title": "重复输入",
            "content": "正文",
        },
    )

    assert response.status_code == 422


def test_accepts_city_intelligence_sync_request(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setattr(
        "trip_agent.guide_intelligence.api.GuideImportService",
        StubImportService,
    )

    response = TestClient(app).post(
        "/internal/v1/guide-imports",
        headers={"X-Internal-Token": "test-internal-token"},
        json={
            "sourceType": "CITY_INTELLIGENCE",
            "city": "广州",
            "startDate": "2026-08-01",
            "endDate": "2026-08-02",
        },
    )

    assert response.status_code == 200
    assert response.json()["sourceType"] == "CITY_INTELLIGENCE"
    assert response.json()["sourceHost"] == "高德城市情报"


def test_accepts_registered_official_source_request(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setattr(
        "trip_agent.guide_intelligence.api.GuideImportService",
        StubImportService,
    )

    response = TestClient(app).post(
        "/internal/v1/guide-imports",
        headers={"X-Internal-Token": "test-internal-token"},
        json={
            "sourceUrl": "https://museum.example/visit",
            "sourceType": "OFFICIAL_ATTRACTION",
            "sourceName": "广州博物馆",
            "city": "广州",
        },
    )

    assert response.status_code == 200
    assert response.json()["sourceType"] == "OFFICIAL_ATTRACTION"
    assert response.json()["title"] == "广州博物馆"


def _png_payload_base64() -> str:
    import base64
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (96, 96)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_accepts_image_ocr_import_with_base64_images(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setattr(
        "trip_agent.guide_intelligence.api.GuideImportService",
        StubImportService,
    )

    response = TestClient(app).post(
        "/internal/v1/guide-imports",
        headers={"X-Internal-Token": "test-internal-token"},
        json={
            "sourceType": "IMAGE_OCR",
            "images": [
                {
                    "dataBase64": _png_payload_base64(),
                    "filename": "guide.png",
                    "contentType": "image/png",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["sourceType"] == "IMAGE_OCR"
    assert response.json()["sourceHost"] == "用户图片截图"


def test_rejects_image_import_without_images(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setattr(
        "trip_agent.guide_intelligence.api.GuideImportService",
        StubImportService,
    )

    response = TestClient(app).post(
        "/internal/v1/guide-imports",
        headers={"X-Internal-Token": "test-internal-token"},
        json={"sourceType": "IMAGE_OCR"},
    )

    assert response.status_code == 422


def test_rejects_image_import_mixed_with_text_fields(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")

    response = TestClient(app).post(
        "/internal/v1/guide-imports",
        headers={"X-Internal-Token": "test-internal-token"},
        json={
            "sourceType": "IMAGE_OCR",
            "title": "混合输入",
            "content": "正文",
            "images": [{"dataBase64": _png_payload_base64()}],
        },
    )

    assert response.status_code == 422


def test_rejects_images_on_non_image_source_types(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")

    response = TestClient(app).post(
        "/internal/v1/guide-imports",
        headers={"X-Internal-Token": "test-internal-token"},
        json={
            "sourceType": "PASTED_TEXT",
            "title": "普通粘贴",
            "content": "广州塔地址是阅江西路222号。",
            "images": [{"dataBase64": _png_payload_base64()}],
        },
    )

    assert response.status_code == 422


def test_maps_ocr_not_configured_to_actionable_detail(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")

    class OcrFailingService(StubImportService):
        async def import_images(self, *, images):
            raise OcrError("OCR_NOT_CONFIGURED", "图片识别未配置。")

    monkeypatch.setattr(
        "trip_agent.guide_intelligence.api.GuideImportService",
        OcrFailingService,
    )

    response = TestClient(app).post(
        "/internal/v1/guide-imports",
        headers={"X-Internal-Token": "test-internal-token"},
        json={
            "sourceType": "IMAGE_OCR",
            "images": [{"dataBase64": _png_payload_base64()}],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"].startswith("OCR_NOT_CONFIGURED:")
