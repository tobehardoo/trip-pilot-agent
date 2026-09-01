"""Content-security filter for guide-import pipeline.

Runs between extraction and validation so that malicious or suspicious
candidates never reach the trusted-fact pipeline or quality scoring.

All functions are side-effect-free and accept immutable inputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trip_agent.guide_intelligence.trusted_facts import CandidateFact

# ── SQL injection patterns ──────────────────────────────────────────────

_SQL_INJECTION = re.compile(
    r"\b(DROP\s+TABLE|INSERT\s+INTO|DELETE\s+FROM|UNION\s+(?:ALL\s+)?SELECT"
    r"|UPDATE\s+\S+\s+SET|ALTER\s+TABLE|TRUNCATE\s+TABLE"
    r"|EXEC(?:UTE)?\s*(?:sp_|\()|\bOR\s+['\"]?\d['\"]?\s*=\s*['\"]?\d"
    r"|SELECT\s+(?:\*|@@|CURRENT_USER|DATABASE\()"
    r"|\bSLEEP\s*\(\s*\d+\s*\))",
    re.IGNORECASE,
)

# Classic tautology bypass patterns
_SQL_TAUTOLOGY = re.compile(
    r"['\"]\s*OR\s+['\"][^'\"]*['\"]\s*=\s*['\"]|"
    r"['\"]\s*OR\s+['\"]\d['\"]\s*=\s*['\"]\d['\"]|"
    r"\bOR\s+\d\s*=\s*\d\s*--",
    re.IGNORECASE,
)

# ── Script / HTML injection ─────────────────────────────────────────────

_SCRIPT_PATTERNS = re.compile(
    r"<\s*script[\s>/]|"
    r"javascript\s*:|"
    r"\bon(?:error|load|click|mouse|focus|blur|submit)\s*=|"
    r"<\s*iframe[\s>/]|"
    r"<\s*embed[\s>/]|"
    r"<\s*object[\s>/]|"
    r"<\s*form[\s>/]|"
    r"data\s*:\s*text\s*/\s*html",
    re.IGNORECASE,
)

_HTML_ENTITY_INJECTION = re.compile(r"&#\d{2,};|&#x[0-9a-f]{2,};", re.IGNORECASE)

# ── Suspicious URL ──────────────────────────────────────────────────────

_URL_PATTERN = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)

_SHORTLINK_DOMAINS = frozenset({
    "bit.ly", "tinyurl.com", "t.co", "ow.ly", "is.gd", "buff.ly",
    "goo.gl", "shorte.st", "bc.vc", "adf.ly", "short.link",
})

_IP_URL = re.compile(r"https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:[:/]|$)")

# ── Control characters ──────────────────────────────────────────────────

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Unicode bidi-override and other dangerous formatting chars
_BIDI_OVERRIDE = re.compile(r"[‪-‮⁦-⁩]")

# ── Repetitive content ──────────────────────────────────────────────────

_REPETITIVE = re.compile(r"(.)\1{199,}")  # same char repeated 200+ times

# ── Length limits ───────────────────────────────────────────────────────

MAX_STATEMENT_LENGTH = 2_000
MAX_EVIDENCE_LENGTH = 3_000


@dataclass(frozen=True, slots=True)
class SecurityFilterResult:
    passed: tuple[CandidateFact, ...]
    blocked: tuple[BlockedCandidate, ...]


@dataclass(frozen=True, slots=True)
class BlockedCandidate:
    candidate: CandidateFact
    rule: str        # e.g. "SECURITY_SQL_INJECTION"
    detail: str      # human-readable explanation


@dataclass(frozen=True, slots=True)
class _RuleResult:
    """Internal accumulator for a single candidate's rule checks."""

    blocked_rules: list[tuple[str, str]] = field(default_factory=list)


def filter_content(
    candidates: tuple[CandidateFact, ...],
) -> SecurityFilterResult:
    """Screen extracted candidate facts for malicious or suspicious content.

    Returns a SecurityFilterResult with accepted candidates in ``passed``
    and blocked candidates (with rule codes) in ``blocked``.
    """
    passed: list[CandidateFact] = []
    blocked: list[BlockedCandidate] = []

    for candidate in candidates:
        text = f"{candidate.statement} {candidate.evidence}"
        result = _check_rules(text, candidate)

        if result.blocked_rules:
            # Report the first (most severe) blocking rule
            rule, detail = result.blocked_rules[0]
            blocked.append(
                BlockedCandidate(candidate=candidate, rule=rule, detail=detail)
            )
        else:
            passed.append(candidate)

    return SecurityFilterResult(
        passed=tuple(passed),
        blocked=tuple(blocked),
    )


def _check_rules(text: str, candidate: CandidateFact) -> _RuleResult:
    result = _RuleResult()

    # ── 1. SQL injection (CRITICAL) ──────────────────────────────────
    sql_match = _SQL_INJECTION.search(text)
    tautology_match = _SQL_TAUTOLOGY.search(text)
    if sql_match:
        result.blocked_rules.append((
            "SECURITY_SQL_INJECTION",
            f"possible SQL injection pattern: '{sql_match.group()[:60]}'",
        ))
    elif tautology_match:
        result.blocked_rules.append((
            "SECURITY_SQL_INJECTION",
            f"SQL tautology or bypass pattern: '{tautology_match.group()[:60]}'",
        ))

    # ── 2. Script / HTML injection (CRITICAL) ────────────────────────
    script_match = _SCRIPT_PATTERNS.search(text)
    html_entity = _HTML_ENTITY_INJECTION.search(text)
    if script_match:
        result.blocked_rules.append((
            "SECURITY_SCRIPT_INJECTION",
            f"script or HTML injection pattern: '{script_match.group()[:60]}'",
        ))
    elif html_entity:
        result.blocked_rules.append((
            "SECURITY_SCRIPT_INJECTION",
            f"encoded HTML entity injection: '{html_entity.group()[:40]}'",
        ))

    # ── 3. Suspicious URLs in statement/evidence ─────────────────────
    urls = _URL_PATTERN.findall(text)
    for url in urls:
        if not url.lower().startswith("https://"):
            result.blocked_rules.append((
                "SECURITY_UNSAFE_URL",
                f"non-HTTPS URL in fact content: '{url[:80]}'",
            ))
            break
        if _IP_URL.match(url):
            result.blocked_rules.append((
                "SECURITY_UNSAFE_URL",
                f"raw-IP URL in fact content: '{url[:80]}'",
            ))
            break
        # Check shortlink domains
        try:
            host = url.split("://", 1)[1].split("/", 1)[0].split(":")[0].lower()
            if host in _SHORTLINK_DOMAINS or any(
                host.endswith(f".{d}") for d in _SHORTLINK_DOMAINS
            ):
                result.blocked_rules.append((
                    "SECURITY_UNSAFE_URL",
                    f"shortlink or untrusted domain in fact: '{url[:80]}'",
                ))
                break
        except (IndexError, ValueError):
            pass

    # ── 4. Control characters ────────────────────────────────────────
    ctrl_match = _CONTROL_CHARS.search(text)
    bidi_match = _BIDI_OVERRIDE.search(text)
    if ctrl_match:
        result.blocked_rules.append((
            "SECURITY_CONTROL_CHARACTERS",
            f"control character 0x{ord(ctrl_match.group()):02x} in fact content",
        ))
    elif bidi_match:
        result.blocked_rules.append((
            "SECURITY_CONTROL_CHARACTERS",
            f"Unicode bidi-override character U+{ord(bidi_match.group()):04X}",
        ))

    # ── 5. Repetitive ────────────────────────────────────────────────
    rep_match = _REPETITIVE.search(text)
    if rep_match:
        result.blocked_rules.append((
            "SECURITY_REPETITIVE_CONTENT",
            f"character '{rep_match.group()[0]}' repeated {len(rep_match.group())} times",
        ))

    # ── 6. Length ────────────────────────────────────────────────────
    max_stmt = len(candidate.statement) if candidate.statement else 0
    max_ev = len(candidate.evidence) if candidate.evidence else 0
    if max_stmt > MAX_STATEMENT_LENGTH:
        result.blocked_rules.append((
            "SECURITY_EXCESSIVE_LENGTH",
            f"statement length {max_stmt} exceeds {MAX_STATEMENT_LENGTH}",
        ))
    elif max_ev > MAX_EVIDENCE_LENGTH:
        result.blocked_rules.append((
            "SECURITY_EXCESSIVE_LENGTH",
            f"evidence length {max_ev} exceeds {MAX_EVIDENCE_LENGTH}",
        ))

    return result
