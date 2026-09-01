"""B2 — opening-hours resolver semantics (tiers, conflicts, WEEKLY partial,
TODAY applicability, runtime freshness) and evidence adapters."""

from datetime import UTC, date, datetime, time, timedelta

from trip_agent.guide_intelligence.opening_evidence import (
    OpeningHoursEvidence,
    evidence_from_amap_poi,
    evidence_from_travel_fact,
    evidence_from_validated_fact,
)
from trip_agent.guide_intelligence.opening_hours import parse_opening_text
from trip_agent.guide_intelligence.opening_resolver import (
    ResolvedOpeningHours,
    resolve_opening_hours,
)
from trip_agent.guide_intelligence.trusted_facts import ValidatedFact

AS_OF = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
CHECKED = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
FRESH_UNTIL = AS_OF + timedelta(days=10)
STALE_SINCE = AS_OF - timedelta(days=1)


def _hm(hour: int, minute: int = 0) -> time:
    return time(hour, minute)


def _evidence(
    *,
    poi_key: str = "POI-1",
    parsed=None,
    raw: str = "raw text",
    effective_date: date | None = None,
    reliability_level: str = "OFFICIAL_ATTRACTION",
    source_reviewed: bool = True,
    hard_constraint_eligible: bool = True,
    confidence: float = 0.9,
    checked_at: datetime = CHECKED,
    expires_at: datetime = FRESH_UNTIL,
    kind: str = "OPENING_HOURS",
    source_ref: str = "fact-1",
) -> OpeningHoursEvidence:
    return OpeningHoursEvidence(
        kind=kind,  # type: ignore[arg-type]
        poi_key=poi_key,
        parsed_hours=parsed,
        raw=raw,
        effective_date=effective_date,
        source_ref=source_ref,
        reliability_level=reliability_level,
        source_reviewed=source_reviewed,
        hard_constraint_eligible=hard_constraint_eligible,
        confidence=confidence,
        checked_at=checked_at,
        expires_at=expires_at,
    )


def _resolve(
    evidences, *, poi_key: str = "POI-1", trip_date: date = date(2026, 8, 1)
) -> ResolvedOpeningHours:
    return resolve_opening_hours(
        evidences, poi_key=poi_key, trip_date=trip_date, resolver_as_of=AS_OF
    )


# ── happy path and runtime freshness ───────────────────────────────────────


def test_daily_window_resolves_verified_window() -> None:
    parsed = parse_opening_text("09:00-17:00")
    result = _resolve([_evidence(parsed=parsed, raw="09:00-17:00")])
    assert result.state == "VERIFIED_WINDOW"
    assert result.windows == parsed.intervals
    assert result.hard_constraint_eligible is True
    assert result.closed is False


def test_freshness_is_runtime_based_on_resolver_as_of() -> None:
    parsed = parse_opening_text("09:00-17:00")
    fresh = _evidence(parsed=parsed, expires_at=AS_OF + timedelta(hours=1))
    stale = _evidence(parsed=parsed, expires_at=AS_OF - timedelta(hours=1))

    assert _resolve([fresh]).state == "VERIFIED_WINDOW"
    assert _resolve([stale]).state == "STALE"
    assert _resolve([stale]).downgraded_reason == "STALE_EVIDENCE"
    assert _resolve([stale]).hard_constraint_eligible is False


def test_stale_evidence_never_selected_when_fresh_exists() -> None:
    parsed = parse_opening_text("09:00-17:00")
    fresh = _evidence(parsed=parsed, expires_at=FRESH_UNTIL)
    stale = _evidence(parsed=parsed, expires_at=STALE_SINCE)
    result = _resolve([fresh, stale])
    assert result.state == "VERIFIED_WINDOW"
    assert result.selected_evidence is fresh


# ── TODAY applicability ────────────────────────────────────────────────────


def test_today_evidence_applies_only_on_its_own_date() -> None:
    parsed = parse_opening_text("09:00-17:00", scope="TODAY")
    assert parsed is not None
    evidence = _evidence(parsed=parsed, effective_date=date(2026, 8, 1))

    on_day = _resolve([evidence], trip_date=date(2026, 8, 1))
    assert on_day.state == "VERIFIED_WINDOW"

    other_day = _resolve([evidence], trip_date=date(2026, 8, 2))
    assert other_day.state == "UNKNOWN"
    assert other_day.downgraded_reason == "NO_OPENING_HOURS_EVIDENCE"


# ── WEEKLY partial-evidence semantics ──────────────────────────────────────


def test_closed_weekday_is_closed_other_days_unknown() -> None:
    parsed = parse_opening_text("每周一闭馆")
    assert parsed is not None
    evidence = _evidence(parsed=parsed, raw="每周一闭馆")

    monday = _resolve([evidence], trip_date=date(2026, 8, 3))  # 2026-08-03 is Mon
    assert monday.state == "VERIFIED_CLOSED"
    assert monday.closed is True

    tuesday = _resolve([evidence], trip_date=date(2026, 8, 4))
    assert tuesday.state == "UNKNOWN"
    assert tuesday.downgraded_reason == "WEEKDAY_NOT_COVERED"


def test_positive_weekday_rule_opens_only_its_weekdays() -> None:
    parsed = parse_opening_text("周一至周五09:00-17:00")
    assert parsed is not None
    evidence = _evidence(parsed=parsed)

    weekday = _resolve([evidence], trip_date=date(2026, 8, 4))  # Tue
    assert weekday.state == "VERIFIED_WINDOW"
    assert weekday.windows == parsed.weekday_rules[0].intervals

    saturday = _resolve([evidence], trip_date=date(2026, 8, 8))
    assert saturday.state == "UNKNOWN"
    assert saturday.downgraded_reason == "WEEKDAY_NOT_COVERED"


# ── conflicts and tiers ────────────────────────────────────────────────────


def test_same_tier_different_values_are_conflicting_regardless_of_confidence() -> None:
    early = parse_opening_text("09:00-17:00")
    late = parse_opening_text("10:00-18:00")
    evidence_early = _evidence(parsed=early, confidence=0.99)
    evidence_late = _evidence(parsed=late, confidence=0.9)

    result = _resolve([evidence_early, evidence_late])
    assert result.state == "CONFLICTING"
    assert result.downgraded_reason == "CONFLICTING_EVIDENCE"
    assert result.hard_constraint_eligible is False
    assert result.selected_evidence is None


def test_same_tier_same_value_merges() -> None:
    parsed = parse_opening_text("09:00-17:00")
    first = _evidence(parsed=parsed, confidence=0.8)
    second = _evidence(parsed=parsed, confidence=0.99)

    result = _resolve([first, second])
    assert result.state == "VERIFIED_WINDOW"
    assert result.selected_evidence is second  # higher confidence representative


def test_same_semantics_different_raw_text_do_not_conflict() -> None:
    """Acceptance fix 2: raw wording must never cause a false conflict."""
    parsed_a = parse_opening_text("开放时间09:00-17:00")
    parsed_b = parse_opening_text("每日 09:00 至 17:00")
    assert parsed_a is not None and parsed_b is not None
    assert parsed_a.intervals == parsed_b.intervals

    result = _resolve(
        [
            _evidence(parsed=parsed_a, raw="开放时间09:00-17:00"),
            _evidence(parsed=parsed_b, raw="每日 09:00 至 17:00"),
        ]
    )
    assert result.state == "VERIFIED_WINDOW"
    assert result.downgraded_reason is None


def test_same_semantics_with_different_effective_dates_conflict() -> None:
    """effective_date participates in the semantic key: two applicable DAILY
    evidences with different effective dates are a real semantic conflict."""
    parsed = parse_opening_text("09:00-17:00")
    assert parsed is not None
    open_any_day = _evidence(parsed=parsed, effective_date=None)
    open_one_date = _evidence(parsed=parsed, effective_date=date(2026, 8, 1))
    result = _resolve([open_any_day, open_one_date])
    assert result.state == "CONFLICTING"
    assert result.hard_constraint_eligible is False


def test_higher_tier_wins_across_tiers_and_lower_tier_is_recorded() -> None:
    official = parse_opening_text("09:00-17:00")
    guide = parse_opening_text("10:00-18:00")
    eligible = _evidence(parsed=official, hard_constraint_eligible=True)
    reviewed = _evidence(
        parsed=guide,
        hard_constraint_eligible=False,
        source_reviewed=True,
        reliability_level="PUBLIC_GUIDE",
    )

    result = _resolve([reviewed, eligible])
    assert result.state == "VERIFIED_WINDOW"
    assert result.selected_evidence is eligible
    assert result.conflict_evidences == (reviewed,)


def test_unreviewed_never_beats_reviewed_or_eligible() -> None:
    parsed = parse_opening_text("09:00-17:00")
    unreviewed = _evidence(parsed=parsed, source_reviewed=False, hard_constraint_eligible=False)
    reviewed = _evidence(parsed=parsed, source_reviewed=True, hard_constraint_eligible=False)
    result = _resolve([unreviewed, reviewed])
    assert result.state == "VERIFIED_WINDOW"
    assert result.selected_evidence is reviewed


# ── UNKNOWN family ─────────────────────────────────────────────────────────


def test_no_evidence_is_unknown() -> None:
    result = _resolve([])
    assert result.state == "UNKNOWN"
    assert result.downgraded_reason == "NO_OPENING_HOURS_EVIDENCE"
    assert result.hard_constraint_eligible is False


def test_unparseable_raw_is_unknown_with_evidence_kept() -> None:
    evidence = _evidence(parsed=None, raw="旺季8:00-18:00")
    result = _resolve([evidence])
    assert result.state == "UNKNOWN"
    assert result.downgraded_reason == "UNPARSEABLE_OPENING_TEXT"
    assert result.conflict_evidences == (evidence,)


def test_all_day_resolves_window_without_intervals() -> None:
    parsed = parse_opening_text("全天开放")
    result = _resolve([_evidence(parsed=parsed)])
    assert result.state == "VERIFIED_WINDOW"
    assert result.windows is None
    assert result.all_day is True


def test_rest_day_resolves_closed() -> None:
    parsed = parse_opening_text("休息")
    result = _resolve([_evidence(parsed=parsed)])
    assert result.state == "VERIFIED_CLOSED"
    assert result.closed is True


def test_last_entry_is_carried_through() -> None:
    parsed = parse_opening_text("09:00-17:00，16:00停止入场")
    result = _resolve([_evidence(parsed=parsed)])
    assert result.state == "VERIFIED_WINDOW"
    assert result.last_entry == _hm(16)


# ── temporary closure channel ──────────────────────────────────────────────


def test_temporary_closure_is_closed_by_kind_not_by_closed_flag() -> None:
    closure = _evidence(
        kind="TEMPORARY_CLOSURE",
        parsed=None,
        raw="8月1日临时闭馆",
        effective_date=date(2026, 8, 1),
    )
    result = _resolve([closure])
    assert result.state == "VERIFIED_CLOSED"
    assert result.closed is True
    assert result.hard_constraint_eligible is True


def test_stale_temporary_closure_on_other_date_does_not_affect_result() -> None:
    """Acceptance fix 3: a stale closure whose effective date misses the trip
    date must not produce STALE and must not enter conflict provenance."""
    stale_closure = _evidence(
        kind="TEMPORARY_CLOSURE",
        parsed=None,
        raw="7月31日临时闭馆",
        effective_date=date(2026, 7, 31),
        expires_at=STALE_SINCE,
    )
    alone = _resolve([stale_closure])
    assert alone.state == "UNKNOWN"
    assert alone.downgraded_reason == "NO_OPENING_HOURS_EVIDENCE"

    parsed = parse_opening_text("09:00-17:00")
    with_opening = _resolve(
        [stale_closure, _evidence(parsed=parsed, expires_at=FRESH_UNTIL)]
    )
    assert with_opening.state == "VERIFIED_WINDOW"
    assert with_opening.conflict_evidences == ()


def test_applicable_expired_closure_alone_is_stale() -> None:
    """Acceptance fix 3 Case B: only an applicable expired TEMPORARY_CLOSURE
    resolves to STALE — it must not collapse into UNKNOWN."""
    expired_closure = _evidence(
        kind="TEMPORARY_CLOSURE",
        parsed=None,
        raw="8月1日临时闭馆",
        effective_date=date(2026, 8, 1),  # hits trip_date
        expires_at=STALE_SINCE,
    )
    result = _resolve([expired_closure])
    assert result.state == "STALE"
    assert result.downgraded_reason == "STALE_EVIDENCE"
    assert result.hard_constraint_eligible is False


def test_expired_closure_with_fresh_opening_keeps_closure_in_provenance() -> None:
    """Acceptance fix 3 Case C: fresh opening hours resolve normally, but an
    applicable expired closure is preserved in conflict_evidences and never
    becomes a hard close."""
    expired_closure = _evidence(
        kind="TEMPORARY_CLOSURE",
        parsed=None,
        raw="8月1日临时闭馆",
        effective_date=date(2026, 8, 1),
        expires_at=STALE_SINCE,
    )
    parsed = parse_opening_text("09:00-17:00")
    fresh_opening = _evidence(parsed=parsed, expires_at=FRESH_UNTIL)

    result = _resolve([expired_closure, fresh_opening])
    assert result.state == "VERIFIED_WINDOW"
    assert result.closed is False
    assert result.selected_evidence is fresh_opening
    assert result.conflict_evidences == (expired_closure,)  # stale closure visible


def test_closure_beats_opening_hours_for_the_same_day() -> None:
    parsed = parse_opening_text("09:00-17:00")
    closure = _evidence(
        kind="TEMPORARY_CLOSURE",
        parsed=None,
        raw="8月1日临时闭馆",
        effective_date=date(2026, 8, 1),
    )
    opening = _evidence(parsed=parsed)
    result = _resolve([opening, closure])
    assert result.state == "VERIFIED_CLOSED"
    assert result.selected_evidence is closure


# ── adapters ───────────────────────────────────────────────────────────────


def _validated_fact(**overrides: object) -> ValidatedFact:
    values = {
        "fact_id": "fact_abc",
        "document_id": "doc-1",
        "category": "OPENING_HOURS",
        "statement": "开放时间：09:00-17:00。",
        "normalized_value": {
            "openTime": "09:00",
            "closeTime": "17:00",
            "scope": "DAILY",
            "openingWindows": [
                {"open": "09:00", "close": "17:00", "closeDayOffset": 0}
            ],
            "raw": "开放时间：09:00-17:00。",
        },
        "evidence": "开放时间：09:00-17:00。",
        "evidence_start": 0,
        "evidence_end": 13,
        "confidence": 0.9,
        "checked_at": CHECKED,
        "expires_at": FRESH_UNTIL,
        "effective_date": None,
        "source_type": "OFFICIAL_ATTRACTION_HTML",
        "source_name": "gz.gov.cn",
        "source_url": "https://www.gz.gov.cn/example",
        "reliability_level": "OFFICIAL_ATTRACTION",
        "source_reviewed": True,
        "hard_constraint_eligible": True,
    }
    values.update(overrides)
    return ValidatedFact(**values)  # type: ignore[arg-type]


def test_validated_fact_adapter_requires_injected_poi_key() -> None:
    assert evidence_from_validated_fact(_validated_fact(), poi_key=None) is None
    evidence = evidence_from_validated_fact(_validated_fact(), poi_key="POI-1")
    assert evidence is not None
    assert evidence.kind == "OPENING_HOURS"
    assert evidence.poi_key == "POI-1"
    assert evidence.hard_constraint_eligible is True
    assert evidence.parsed_hours is not None
    assert evidence.parsed_hours.intervals[0].open == _hm(9)


def test_validated_fact_adapter_marks_temporary_closure_kind() -> None:
    fact = _validated_fact(
        category="TEMPORARY_CLOSURE",
        normalized_value={"closed": True},
        effective_date=date(2026, 8, 1),
    )
    evidence = evidence_from_validated_fact(fact, poi_key="POI-1")
    assert evidence is not None
    assert evidence.kind == "TEMPORARY_CLOSURE"
    assert evidence.parsed_hours is None


def test_amap_poi_adapter_binds_today_to_passed_fetch_time() -> None:
    """Acceptance fix 1: the fetch time is passed explicitly to the adapter;
    Poi itself does not carry it.  Different search batches derive different
    TODAY effective dates from their own ProviderSuccess.fetched_at."""
    from trip_agent.providers.map import Coordinates, Poi

    poi = Poi(
        provider_id="B001",
        name="陈家祠",
        coordinates=Coordinates(longitude=113.246, latitude=23.129),
        type_name="科教文化服务;博物馆",
        type_code="140100",
        province="广东省",
        city="广州市",
        district="荔湾区",
        address="中山七路",
        business_hours_today="09:00-17:00",
        business_hours_week="一,二,三,四,五,六,日|09:00-17:00",
    )
    assert "fetched_at" not in poi.model_dump()  # Poi must not hold fetch time

    # Batch 1 fetched 2026-07-25 20:30 UTC == 2026-07-26 04:30 +08
    batch_one = evidence_from_amap_poi(
        poi, poi_key="canonical-B001",
        fetched_at=datetime(2026, 7, 25, 20, 30, tzinfo=UTC),
    )
    # Batch 2 fetched a day later
    batch_two = evidence_from_amap_poi(
        poi, poi_key="canonical-B001",
        fetched_at=datetime(2026, 7, 26, 20, 30, tzinfo=UTC),
    )
    assert len(batch_one) == 2
    assert len(batch_two) == 2

    today_one = next(item for item in batch_one if item.effective_date is not None)
    today_two = next(item for item in batch_two if item.effective_date is not None)
    assert today_one.effective_date == date(2026, 7, 26)
    assert today_two.effective_date == date(2026, 7, 27)
    assert today_one.parsed_hours is not None
    assert today_one.parsed_hours.scope == "TODAY"
    assert today_one.reliability_level == "MAP_PROVIDER"
    assert today_one.source_reviewed is False
    assert today_one.hard_constraint_eligible is False

    weekly_one = next(item for item in batch_one if item.effective_date is None)
    assert weekly_one.parsed_hours is not None
    assert weekly_one.parsed_hours.scope == "WEEKLY"
    assert weekly_one.parsed_hours.weekday_rules[0].weekdays == frozenset(range(7))


def test_travel_fact_adapter_uses_fixed_provenance_and_today_date() -> None:
    from trip_agent.guide_intelligence.models import TravelFact

    fact = TravelFact(
        category="TIMING",
        statement="陈家祠今日营业信息：09:00-17:00。",
        evidence="陈家祠今日营业信息：09:00-17:00。",
        confidence=0.8,
        observed_at=CHECKED,
        expires_at=FRESH_UNTIL,
        normalized_value={
            "scope": "TODAY",
            "effectiveDate": "2026-07-30",
            "openingWindows": [
                {"open": "09:00", "close": "17:00", "closeDayOffset": 0}
            ],
            "raw": "09:00-17:00",
        },
    )
    evidence = evidence_from_travel_fact(fact, poi_key="POI-1", source_name="city-intel")
    assert evidence is not None
    assert evidence.kind == "OPENING_HOURS"
    assert evidence.reliability_level == "MAP_PROVIDER"
    assert evidence.source_reviewed is False
    assert evidence.hard_constraint_eligible is False
    assert evidence.effective_date == date(2026, 7, 30)
    assert evidence.parsed_hours is not None
    assert evidence.parsed_hours.scope == "TODAY"


def test_travel_fact_adapter_ignores_non_timing_facts() -> None:
    from trip_agent.guide_intelligence.models import TravelFact

    fact = TravelFact(
        category="WEATHER",
        statement="广州雷阵雨",
        evidence="广州雷阵雨",
        confidence=0.9,
        observed_at=CHECKED,
        expires_at=FRESH_UNTIL,
    )
    assert evidence_from_travel_fact(fact, poi_key="POI-1", source_name="city-intel") is None


# ── consumption contract guard ─────────────────────────────────────────────


def test_hard_eligibility_only_for_verified_resolved_states() -> None:
    parsed = parse_opening_text("09:00-17:00")
    eligible = _evidence(parsed=parsed, hard_constraint_eligible=True)
    conflicting_other = _evidence(
        parsed=parse_opening_text("10:00-18:00"),
        hard_constraint_eligible=True,
    )

    verified = _resolve([eligible])
    assert verified.state == "VERIFIED_WINDOW"
    assert verified.hard_constraint_eligible is True

    conflicting = _resolve([eligible, conflicting_other])
    assert conflicting.state == "CONFLICTING"
    assert conflicting.hard_constraint_eligible is False


# ── B5.2: temporary-closure hard-eligibility basis ─────────────────────────


def _closure(
    *,
    confidence: float,
    eligible: bool,
    source_ref: str,
    effective_date: date | None = date(2026, 8, 1),
) -> OpeningHoursEvidence:
    return _evidence(
        kind="TEMPORARY_CLOSURE",
        parsed=None,
        raw=f"closure {source_ref}",
        effective_date=effective_date,
        hard_constraint_eligible=eligible,
        confidence=confidence,
        source_ref=source_ref,
    )


def test_closure_selected_basis_is_eligible_when_available() -> None:
    high_ineligible = _closure(confidence=0.99, eligible=False, source_ref="high")
    low_eligible = _closure(confidence=0.80, eligible=True, source_ref="low")

    result = _resolve([high_ineligible, low_eligible])

    assert result.state == "VERIFIED_CLOSED"
    assert result.hard_constraint_eligible is True
    assert result.selected_evidence is low_eligible
    assert result.selected_evidence.hard_constraint_eligible is True
    assert all(evidence is not result.selected_evidence for evidence in result.conflict_evidences)
    assert high_ineligible in result.conflict_evidences


def test_closure_no_eligible_yields_ineligible_selected() -> None:
    first = _closure(confidence=0.99, eligible=False, source_ref="a")
    second = _closure(confidence=0.80, eligible=False, source_ref="b")

    result = _resolve([first, second])

    assert result.hard_constraint_eligible is False
    assert result.selected_evidence is first  # confidence max among equals
    assert result.selected_evidence.hard_constraint_eligible is False


def test_multiple_eligible_closures_select_highest_confidence_eligible() -> None:
    low = _closure(confidence=0.80, eligible=True, source_ref="low")
    high = _closure(confidence=0.90, eligible=True, source_ref="high")

    result = _resolve([low, high])

    assert result.selected_evidence is high
    assert result.selected_evidence.hard_constraint_eligible is True


def test_closure_selection_is_order_independent() -> None:
    high_ineligible = _closure(confidence=0.99, eligible=False, source_ref="high")
    low_eligible = _closure(confidence=0.80, eligible=True, source_ref="low")

    forward = _resolve([high_ineligible, low_eligible])
    backward = _resolve([low_eligible, high_ineligible])

    assert forward.selected_evidence is backward.selected_evidence
    assert {id(e) for e in forward.conflict_evidences} == {
        id(e) for e in backward.conflict_evidences
    }


# ── B5.3: stable tie-break for identical eligibility/confidence ────────────


def test_same_confidence_eligible_closures_select_stably() -> None:
    a = _closure(confidence=0.90, eligible=True, source_ref="a")
    b = _closure(confidence=0.90, eligible=True, source_ref="b")

    forward = _resolve([a, b])
    backward = _resolve([b, a])

    assert forward.selected_evidence is backward.selected_evidence
    assert {id(e) for e in forward.conflict_evidences} == {
        id(e) for e in backward.conflict_evidences
    }


def test_same_confidence_ineligible_closures_select_stably() -> None:
    a = _closure(confidence=0.90, eligible=False, source_ref="a")
    b = _closure(confidence=0.90, eligible=False, source_ref="b")

    forward = _resolve([a, b])
    backward = _resolve([b, a])

    assert forward.selected_evidence is backward.selected_evidence
    assert forward.selected_evidence.hard_constraint_eligible is False
    assert {id(e) for e in forward.conflict_evidences} == {
        id(e) for e in backward.conflict_evidences
    }
