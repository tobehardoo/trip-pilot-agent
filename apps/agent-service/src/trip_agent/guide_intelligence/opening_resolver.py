"""Opening-hours resolver — resolves evidence into one state per POI/date.

Pure, deterministic, read-only.  The resolver never mutates anything and
never decides a repair; it only produces the state a future hard validator
may consume.

Consumption contract (locked)
-----------------------------
A resolved state may feed HARD validation **only** when::

    state in {"VERIFIED_WINDOW", "VERIFIED_CLOSED"}
    and hard_constraint_eligible is True

``UNKNOWN``, ``CONFLICTING``, and ``STALE`` are always downgraded — the
resolver has no silent hard-fail path.

Tier semantics
--------------
Tier3 = fresh + applicable + ``hard_constraint_eligible``
Tier2 = fresh + applicable + ``source_reviewed`` (not eligible)
Tier1 = fresh + applicable (everything else)

Within the highest non-empty tier, identical semantic values may be merged;
different values are always ``CONFLICTING`` — confidence, source type, and
checked_at never silently break a same-tier conflict.

WEEKLY partial-evidence semantics
---------------------------------
Only ``closed_weekdays`` yields VERIFIED_CLOSED and only a positive
``weekday_rules`` match yields VERIFIED_WINDOW.  A day not covered by either
is UNKNOWN — closed-weekday rules are never inverted into "open".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal

from trip_agent.guide_intelligence.opening_evidence import (
    OpeningHoursEvidence,
)
from trip_agent.guide_intelligence.opening_hours import (
    TimeInterval,
)

type ResolvedState = Literal[
    "VERIFIED_WINDOW",
    "VERIFIED_CLOSED",
    "UNKNOWN",
    "CONFLICTING",
    "STALE",
]


@dataclass(frozen=True, slots=True)
class ResolvedOpeningHours:
    poi_key: str
    date: date
    state: ResolvedState
    windows: tuple[TimeInterval, ...] | None
    last_entry: time | None
    closed: bool
    all_day: bool
    hard_constraint_eligible: bool
    selected_evidence: OpeningHoursEvidence | None
    conflict_evidences: tuple[OpeningHoursEvidence, ...]
    downgraded_reason: str | None


def resolve_opening_hours(
    evidences: Iterable[OpeningHoursEvidence],
    *,
    poi_key: str,
    trip_date: date,
    resolver_as_of: datetime,
) -> ResolvedOpeningHours:
    """Resolve opening-hours evidence for one POI on one trip date.

    ``resolver_as_of`` is the single runtime freshness clock; any evidence
    with ``expires_at <= resolver_as_of`` is stale.  The timestamp must be
    timezone-aware.
    """
    if resolver_as_of.tzinfo is None or resolver_as_of.utcoffset() is None:
        raise ValueError("resolver_as_of must be timezone-aware")

    matches = tuple(
        evidence
        for evidence in evidences
        if evidence.poi_key == poi_key
    )

    # -- TEMPORARY_CLOSURE channel: kind-based priority, never inferred from
    #    a closed=True flag.  Applicability (effective date) is decided first,
    #    then freshness — an applicable expired closure stays visible for the
    #    STALE state and for conflict provenance below.
    closure_applicable = tuple(
        evidence
        for evidence in matches
        if evidence.kind == "TEMPORARY_CLOSURE"
        and (evidence.effective_date is None or evidence.effective_date == trip_date)
    )
    closure_fresh = tuple(
        evidence for evidence in closure_applicable
        if evidence.expires_at > resolver_as_of
    )
    closure_stale = tuple(
        evidence for evidence in closure_applicable
        if evidence.expires_at <= resolver_as_of
    )
    if closure_fresh:
        # The verdict basis must itself carry the hard-eligibility: prefer
        # eligible closures, then highest confidence, so a high-confidence
        # ineligible closure never steals the VERIFIED/True basis.  The
        # remaining provenance fields make the choice fully deterministic —
        # identical eligibility/confidence never depends on input order.
        eligible_closure = tuple(
            evidence for evidence in closure_fresh if evidence.hard_constraint_eligible
        )
        pool = eligible_closure if eligible_closure else closure_fresh
        selected = max(
            pool,
            key=lambda item: (
                item.hard_constraint_eligible,
                item.confidence,
                item.source_ref,
                item.checked_at,
                item.expires_at,
            ),
        )
        return ResolvedOpeningHours(
            poi_key=poi_key,
            date=trip_date,
            state="VERIFIED_CLOSED",
            windows=None,
            last_entry=None,
            closed=True,
            all_day=False,
            hard_constraint_eligible=selected.hard_constraint_eligible,
            selected_evidence=selected,
            conflict_evidences=tuple(
                item for item in closure_fresh if item is not selected
            ),
            downgraded_reason=None,
        )

    # -- OPENING_HOURS channel ----------------------------------------------
    applicable = tuple(
        evidence
        for evidence in matches
        if evidence.kind == "OPENING_HOURS"
        and _is_applicable(evidence, trip_date)
    )
    fresh = tuple(
        evidence for evidence in applicable
        if evidence.expires_at > resolver_as_of
    )
    stale = tuple(
        evidence for evidence in applicable
        if evidence.expires_at <= resolver_as_of
    )
    if not fresh:
        stale_pool = (*stale, *closure_stale)
        if stale_pool:
            return _unknown(
                poi_key, trip_date, stale_pool,
                reason="STALE_EVIDENCE",
                state="STALE",
                stale=stale_pool,
            )
        return _unknown(
            poi_key, trip_date, matches,
            reason="NO_OPENING_HOURS_EVIDENCE",
        )

    tier = _highest_tier(fresh)
    semantic_groups: dict[object, list[OpeningHoursEvidence]] = {}
    for evidence in tier:
        semantic_groups.setdefault(_semantic_value(evidence), []).append(evidence)
    if len(semantic_groups) > 1:
        return _unknown(
            poi_key, trip_date, tier,
            reason="CONFLICTING_EVIDENCE",
            state="CONFLICTING",
            conflict_evidences=tier,
        )
    selected = max(next(iter(semantic_groups.values())), key=lambda item: item.confidence)
    downgraded = tuple(
        evidence for evidence in (*fresh, *closure_stale) if evidence not in tier
    )

    return _judge(selected, poi_key, trip_date, downgraded)


def _is_applicable(evidence: OpeningHoursEvidence, trip_date: date) -> bool:
    """TODAY evidence applies only on its own effective date; DAILY/WEEKLY
    evidence applies on any trip date.  Unparseable evidence stays applicable
    so the resolver can report UNKNOWN with its raw text."""
    parsed = evidence.parsed_hours
    if parsed is None:
        return True
    if parsed.scope == "TODAY":
        return evidence.effective_date == trip_date
    return True


def _highest_tier(
    fresh: tuple[OpeningHoursEvidence, ...],
) -> tuple[OpeningHoursEvidence, ...]:
    eligible = tuple(item for item in fresh if item.hard_constraint_eligible)
    if eligible:
        return eligible
    reviewed = tuple(item for item in fresh if item.source_reviewed)
    if reviewed:
        return reviewed
    return fresh


def _semantic_value(evidence: OpeningHoursEvidence) -> object:
    """The comparison key for same-tier conflict detection.

    Only fields that participate in opening semantics are included: scope,
    intervals, all_day, closed, closed_weekdays, weekday_rules, last_entry,
    and the effective date.  ``raw``, ``note``, ``source_ref``, ``confidence``,
    ``checked_at`` and ``expires_at`` are excluded — two evidences with the
    same business semantics but different wording must never conflict.
    """
    parsed = evidence.parsed_hours
    if parsed is None:
        return ("UNPARSEABLE", evidence.effective_date)
    return (
        parsed.scope,
        parsed.intervals,
        parsed.all_day,
        parsed.closed,
        parsed.closed_weekdays,
        parsed.weekday_rules,
        parsed.last_entry,
        evidence.effective_date,
    )


def _judge(
    selected: OpeningHoursEvidence,
    poi_key: str,
    trip_date: date,
    downgraded: tuple[OpeningHoursEvidence, ...],
) -> ResolvedOpeningHours:
    parsed = selected.parsed_hours
    if parsed is None:
        return _unknown(
            poi_key, trip_date, (selected, *downgraded),
            reason="UNPARSEABLE_OPENING_TEXT",
        )

    # WEEKLY: closed weekday beats everything; positive rule wins only on its
    # own weekdays; any other day is UNKNOWN (never inverted into open).
    if parsed.scope == "WEEKLY":
        weekday = trip_date.weekday()
        if weekday in parsed.closed_weekdays:
            return ResolvedOpeningHours(
                poi_key=poi_key, date=trip_date,
                state="VERIFIED_CLOSED", windows=None, last_entry=None,
                closed=True, all_day=False,
                hard_constraint_eligible=selected.hard_constraint_eligible,
                selected_evidence=selected,
                conflict_evidences=downgraded,
                downgraded_reason=None,
            )
        for rule in parsed.weekday_rules:
            if weekday in rule.weekdays:
                return ResolvedOpeningHours(
                    poi_key=poi_key, date=trip_date,
                    state="VERIFIED_WINDOW", windows=rule.intervals,
                    last_entry=parsed.last_entry, closed=False,
                    all_day=False,
                    hard_constraint_eligible=selected.hard_constraint_eligible,
                    selected_evidence=selected,
                    conflict_evidences=downgraded,
                    downgraded_reason=None,
                )
        return _unknown(
            poi_key, trip_date, (selected, *downgraded),
            reason="WEEKDAY_NOT_COVERED",
        )

    # DAILY / TODAY
    if parsed.all_day:
        return ResolvedOpeningHours(
            poi_key=poi_key, date=trip_date,
            state="VERIFIED_WINDOW", windows=None, last_entry=None,
            closed=False, all_day=True,
            hard_constraint_eligible=selected.hard_constraint_eligible,
            selected_evidence=selected,
            conflict_evidences=downgraded,
            downgraded_reason=None,
        )
    if parsed.closed:
        return ResolvedOpeningHours(
            poi_key=poi_key, date=trip_date,
            state="VERIFIED_CLOSED", windows=None, last_entry=None,
            closed=True, all_day=False,
            hard_constraint_eligible=selected.hard_constraint_eligible,
            selected_evidence=selected,
            conflict_evidences=downgraded,
            downgraded_reason=None,
        )
    if parsed.intervals:
        return ResolvedOpeningHours(
            poi_key=poi_key, date=trip_date,
            state="VERIFIED_WINDOW", windows=parsed.intervals,
            last_entry=parsed.last_entry, closed=False,
            all_day=False,
            hard_constraint_eligible=selected.hard_constraint_eligible,
            selected_evidence=selected,
            conflict_evidences=downgraded,
            downgraded_reason=None,
        )
    return _unknown(
        poi_key, trip_date, (selected, *downgraded),
        reason="UNPARSEABLE_OPENING_TEXT",
    )


def _unknown(
    poi_key: str,
    trip_date: date,
    evidences: tuple[OpeningHoursEvidence, ...],
    *,
    reason: str,
    state: ResolvedState = "UNKNOWN",
    stale: tuple[OpeningHoursEvidence, ...] = (),
    conflict_evidences: tuple[OpeningHoursEvidence, ...] = (),
) -> ResolvedOpeningHours:
    return ResolvedOpeningHours(
        poi_key=poi_key,
        date=trip_date,
        state=state,
        windows=None,
        last_entry=None,
        closed=False,
        all_day=False,
        hard_constraint_eligible=False,
        selected_evidence=None,
        conflict_evidences=conflict_evidences or evidences,
        downgraded_reason=reason,
    )
