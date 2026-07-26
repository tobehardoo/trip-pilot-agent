import asyncio
import json
from datetime import UTC, datetime

import pytest

from trip_agent.guide_intelligence.structured_model import StructuredModelFactExtractor
from trip_agent.guide_intelligence.trusted_facts import DocumentNormalizer

CHECKED_AT = datetime(2026, 7, 26, 8, 30, tzinfo=UTC)


class StubTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls = 0
        self.last_schema: dict[str, object] | None = None

    async def extract(
        self,
        *,
        content: str,
        json_schema: dict[str, object],
        timeout_seconds: float,
    ) -> object:
        self.calls += 1
        self.last_schema = json_schema
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def test_uses_strict_schema_and_returns_candidates_only() -> None:
    document = _document("开放时间：09:00-17:00。")
    transport = StubTransport(
        [
            {
                "facts": [
                    {
                        "category": "OPENING_HOURS",
                        "statement": "景点每日09:00至17:00开放",
                        "normalizedValue": {
                            "openTime": "09:00",
                            "closeTime": "17:00",
                        },
                        "evidence": "开放时间：09:00-17:00。",
                        "evidenceStart": 0,
                        "evidenceEnd": 17,
                        "confidence": 0.91,
                        "effectiveDate": None,
                    }
                ]
            }
        ]
    )

    result = asyncio.run(
        StructuredModelFactExtractor(
            transport=transport,
            timeout_seconds=2,
            max_retries=1,
        ).extract(document, checked_at=CHECKED_AT)
    )

    assert result.status == "EXTRACTED"
    assert len(result.candidates) == 1
    assert result.candidates[0].category == "OPENING_HOURS"
    assert transport.last_schema is not None
    assert transport.last_schema["additionalProperties"] is False


def test_invalid_json_schema_result_is_failed_without_partial_facts() -> None:
    transport = StubTransport(
        [
            json.dumps(
                {
                    "facts": [
                        {
                            "category": "NOT_A_CATEGORY",
                            "statement": "guess",
                            "normalizedValue": {},
                            "evidence": "",
                            "evidenceStart": -1,
                            "evidenceEnd": 999,
                            "confidence": 2,
                            "unexpected": True,
                        }
                    ]
                }
            )
        ]
    )

    result = asyncio.run(
        StructuredModelFactExtractor(
            transport=transport,
            max_retries=0,
        ).extract(_document("没有可提取事实。"), checked_at=CHECKED_AT)
    )

    assert result.status == "FAILED"
    assert result.candidates == ()
    assert result.failure_code == "MODEL_SCHEMA_INVALID"


def test_timeout_retries_are_bounded_and_rule_pipeline_can_continue() -> None:
    transport = StubTransport([TimeoutError(), TimeoutError(), {"facts": []}])
    extractor = StructuredModelFactExtractor(
        transport=transport,
        timeout_seconds=0.1,
        max_retries=1,
    )

    result = asyncio.run(
        extractor.extract(_document("门票10元。"), checked_at=CHECKED_AT)
    )

    assert result.status == "FAILED"
    assert result.failure_code == "MODEL_TIMEOUT"
    assert result.attempts == 2
    assert transport.calls == 2


def test_unconfigured_model_is_explicitly_skipped() -> None:
    result = asyncio.run(
        StructuredModelFactExtractor(transport=None).extract(
            _document("门票10元。"),
            checked_at=CHECKED_AT,
        )
    )

    assert result.status == "SKIPPED"
    assert result.failure_code == "MODEL_NOT_CONFIGURED"


def test_caller_cancellation_is_not_swallowed() -> None:
    transport = StubTransport([asyncio.CancelledError()])

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            StructuredModelFactExtractor(transport=transport).extract(
                _document("门票10元。"),
                checked_at=CHECKED_AT,
            )
        )


def _document(content: str):
    return DocumentNormalizer().normalize_text(
        source_type="PASTED_TEXT",
        source_name="用户粘贴文本",
        source_url=None,
        city="广州",
        title="测试文档",
        content=content,
        fetched_at=CHECKED_AT,
        encoding="utf-8",
        reliability_level="COMMUNITY",
    )
