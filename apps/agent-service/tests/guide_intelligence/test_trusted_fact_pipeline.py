from datetime import UTC, date, datetime, timedelta

import pytest

from trip_agent.guide_intelligence.trusted_facts import (
    CandidateFact,
    DocumentNormalizer,
    FactMerger,
    FactValidator,
    NormalizedDocument,
    RuleFactExtractor,
    ValidatedFact,
)

CHECKED_AT = datetime(2026, 7, 26, 8, 30, tzinfo=UTC)


def test_normalizes_utf8_text_markdown_and_xiaohongshu_without_losing_evidence() -> None:
    normalizer = DocumentNormalizer(max_content_characters=2_000)
    markdown = """
    # 广州塔攻略

    地址：广州市海珠区阅江西路222号。
    门票 150 元，开放时间 09:00-17:00，需要预约。
    复制后打开【小红书】查看笔记！
    https://xhslink.com/abc123
    """

    document = normalizer.normalize_text(
        source_type="XIAOHONGSHU_SHARED_TEXT",
        source_name="用户主动提供的小红书分享正文",
        source_url=None,
        city="广州",
        title="广州塔攻略.md",
        content=markdown,
        fetched_at=CHECKED_AT,
        encoding="utf-8",
        reliability_level="COMMUNITY",
    )

    assert document.document_id.startswith("doc_")
    assert document.title == "广州塔攻略.md"
    assert "地址：广州市海珠区阅江西路222号。" in document.content
    assert "复制后打开" not in document.content
    assert "xhslink.com" not in document.content
    assert document.content_hash
    assert document.language == "zh-CN"


def test_normalizes_official_html_and_rejects_empty_or_oversized_content() -> None:
    normalizer = DocumentNormalizer(max_content_characters=80)
    document = normalizer.normalize_html(
        source_type="OFFICIAL_ATTRACTION_HTML",
        source_name="故宫博物院",
        source_url="https://www.dpm.org.cn/Visit.html",
        city="北京",
        content="""
        <html><head><title>参观导览</title></head><body><main>
        <nav>菜单</nav><p>开放时间：08:30-17:00。</p><script>secret()</script>
        </main></body></html>
        """.encode(),
        content_type="text/html; charset=utf-8",
        fetched_at=CHECKED_AT,
        reliability_level="OFFICIAL_ATTRACTION",
        source_reviewed=True,
    )

    assert document.title == "参观导览"
    assert document.content == "开放时间：08:30-17:00。"
    assert "secret" not in document.content
    with pytest.raises(ValueError, match="empty"):
        normalizer.normalize_text(
            source_type="PASTED_TEXT",
            source_name="粘贴文本",
            source_url=None,
            city="广州",
            title="空内容",
            content=" \n ",
            fetched_at=CHECKED_AT,
            encoding="utf-8",
            reliability_level="COMMUNITY",
        )
    with pytest.raises(ValueError, match="maximum"):
        normalizer.normalize_text(
            source_type="TEXT_FILE",
            source_name="TXT",
            source_url=None,
            city="广州",
            title="too-large.txt",
            content="门票 10 元。" * 20,
            fetched_at=CHECKED_AT,
            encoding="utf-8",
            reliability_level="COMMUNITY",
        )


def test_rule_extractor_emits_normalized_candidates_with_exact_evidence_spans() -> None:
    document = _document(
        "陈家祠地址：广州市荔湾区中山七路恩龙里34号。\n"
        "开放时间：09:00-17:30，成人门票10元，需要提前预约。\n"
        "2026-08-03有雷阵雨，最高温度32℃。"
    )

    candidates = RuleFactExtractor().extract(document, checked_at=CHECKED_AT)

    assert {fact.category for fact in candidates} >= {
        "ADDRESS",
        "OPENING_HOURS",
        "TICKET_PRICE",
        "RESERVATION_REQUIREMENT",
        "WEATHER",
    }
    for fact in candidates:
        assert document.content[fact.evidence_start : fact.evidence_end] == fact.evidence
        assert fact.expires_at > fact.checked_at
    ticket = next(fact for fact in candidates if fact.category == "TICKET_PRICE")
    assert ticket.normalized_value == {"amount": 10.0, "currency": "CNY"}
    opening = next(fact for fact in candidates if fact.category == "OPENING_HOURS")
    assert opening.normalized_value == {"openTime": "09:00", "closeTime": "17:30"}


def test_validator_rejects_missing_evidence_bad_spans_time_money_coordinates_and_expiry() -> None:
    document = _document("开放时间：09:00-17:00。地址：广州市越秀区。")
    candidates = (
        _candidate("OPENING_HOURS", "不存在的证据", 0, 7),
        _candidate(
            "OPENING_HOURS",
            "开放时间：09:00-17:00。",
            0,
            len("开放时间：09:00-17:00。"),
            {"openTime": "17:00", "closeTime": "09:00"},
        ),
        _candidate(
            "TICKET_PRICE",
            "地址：广州市越秀区。",
            20,
            30,
            {"amount": -1, "currency": "CNY"},
        ),
        _candidate(
            "COORDINATES",
            "地址：广州市越秀区。",
            20,
            30,
            {"longitude": 181, "latitude": 23},
        ),
        CandidateFact(
            category="ADDRESS",
            statement="地址：广州市越秀区。",
            normalized_value={"address": "广州市越秀区"},
            evidence="地址：广州市越秀区。",
            evidence_start=20,
            evidence_end=30,
            confidence=0.9,
            checked_at=CHECKED_AT,
            expires_at=CHECKED_AT,
        ),
    )

    result = FactValidator().validate(document, candidates)

    assert result.accepted == ()
    codes = {reason.code for rejected in result.rejected for reason in rejected.reasons}
    assert codes >= {
        "EVIDENCE_MISMATCH",
        "EVIDENCE_SPAN_INVALID",
        "OPENING_HOURS_REVERSED",
        "AMOUNT_INVALID",
        "COORDINATES_INVALID",
        "EXPIRY_INVALID",
    }


def test_validator_requires_reviewed_registry_for_official_strong_facts() -> None:
    content = "故宫博物院2026-08-03临时关闭，参观须提前预约。"
    evidence = content
    candidate = _candidate(
        "TEMPORARY_CLOSURE",
        evidence,
        0,
        len(evidence),
        {"closed": True},
        effective_date=date(2026, 8, 3),
    )
    unreviewed = _document(
        content,
        source_type="OFFICIAL_ATTRACTION_HTML",
        reliability_level="OFFICIAL_ATTRACTION",
        source_reviewed=False,
    )
    reviewed = _document(
        content,
        source_type="OFFICIAL_ATTRACTION_HTML",
        reliability_level="OFFICIAL_ATTRACTION",
        source_reviewed=True,
    )

    assert FactValidator().validate(unreviewed, (candidate,)).accepted == ()
    accepted = FactValidator().validate(
        reviewed,
        (candidate,),
        trip_start=date(2026, 8, 3),
        trip_end=date(2026, 8, 5),
    ).accepted
    assert len(accepted) == 1
    assert accepted[0].hard_constraint_eligible is True


def test_merger_prefers_fresh_reviewed_official_fact_and_explains_conflict() -> None:
    official = _validated(
        fact_id="official-reservation",
        category="RESERVATION_REQUIREMENT",
        value={"required": True, "poiName": "故宫博物院"},
        reliability="OFFICIAL_ATTRACTION",
        checked_at=CHECKED_AT,
        source_reviewed=True,
    )
    community = _validated(
        fact_id="community-reservation",
        category="RESERVATION_REQUIREMENT",
        value={"required": False, "poiName": "故宫"},
        reliability="COMMUNITY",
        checked_at=CHECKED_AT + timedelta(hours=1),
        source_reviewed=False,
    )

    result = FactMerger(aliases={"故宫": "故宫博物院"}).merge((community, official))

    assert len(result.decisions) == 1
    decision = result.decisions[0]
    assert decision.selected_fact.fact_id == "official-reservation"
    assert [fact.fact_id for fact in decision.downgraded_facts] == [
        "community-reservation"
    ]
    assert decision.needs_manual_review is False
    assert "reviewed official" in decision.reason


def test_merger_keeps_different_dates_and_reference_spend_separate() -> None:
    first_day = _validated(
        fact_id="weather-1",
        category="WEATHER",
        value={"condition": "RAIN"},
        reliability="WEATHER_PROVIDER",
        checked_at=CHECKED_AT,
        effective_date=date(2026, 8, 3),
    )
    second_day = _validated(
        fact_id="weather-2",
        category="WEATHER",
        value={"condition": "CLEAR"},
        reliability="WEATHER_PROVIDER",
        checked_at=CHECKED_AT,
        effective_date=date(2026, 8, 4),
    )
    ticket = _validated(
        fact_id="official-ticket",
        category="TICKET_PRICE",
        value={"amount": 0, "currency": "CNY", "poiName": "上海博物馆"},
        reliability="OFFICIAL_ATTRACTION",
        checked_at=CHECKED_AT,
        source_reviewed=True,
    )
    spend = _validated(
        fact_id="amap-spend",
        category="REFERENCE_SPEND",
        value={"amount": 50, "currency": "CNY", "poiName": "上海博物馆"},
        reliability="MAP_PROVIDER",
        checked_at=CHECKED_AT,
    )

    result = FactMerger().merge((first_day, second_day, ticket, spend))

    assert len(result.selected_facts) == 4
    assert all(not decision.conflict_facts for decision in result.decisions)


def _document(
    content: str,
    *,
    source_type: str = "PASTED_TEXT",
    reliability_level: str = "COMMUNITY",
    source_reviewed: bool = False,
) -> NormalizedDocument:
    return DocumentNormalizer().normalize_text(
        source_type=source_type,
        source_name="测试来源",
        source_url=None,
        city="广州",
        title="测试文档",
        content=content,
        fetched_at=CHECKED_AT,
        encoding="utf-8",
        reliability_level=reliability_level,
        source_reviewed=source_reviewed,
    )


def _candidate(
    category: str,
    evidence: str,
    evidence_start: int,
    evidence_end: int,
    value: dict[str, object] | None = None,
    *,
    effective_date: date | None = None,
) -> CandidateFact:
    return CandidateFact(
        category=category,
        statement=evidence,
        normalized_value=value or {},
        evidence=evidence,
        evidence_start=evidence_start,
        evidence_end=evidence_end,
        confidence=0.9,
        checked_at=CHECKED_AT,
        expires_at=CHECKED_AT + timedelta(days=1),
        effective_date=effective_date,
    )


def _validated(
    *,
    fact_id: str,
    category: str,
    value: dict[str, object],
    reliability: str,
    checked_at: datetime,
    source_reviewed: bool = False,
    effective_date: date | None = None,
) -> ValidatedFact:
    return ValidatedFact(
        fact_id=fact_id,
        document_id=f"document-{fact_id}",
        category=category,
        statement=f"{fact_id} statement",
        normalized_value=value,
        evidence=f"{fact_id} evidence",
        evidence_start=0,
        evidence_end=len(f"{fact_id} evidence"),
        confidence=0.9,
        checked_at=checked_at,
        expires_at=checked_at + timedelta(days=3),
        effective_date=effective_date,
        source_type="OFFICIAL_ATTRACTION_HTML" if source_reviewed else "PASTED_TEXT",
        source_name=f"{reliability} source",
        source_url=None,
        reliability_level=reliability,
        source_reviewed=source_reviewed,
        hard_constraint_eligible=source_reviewed,
    )
