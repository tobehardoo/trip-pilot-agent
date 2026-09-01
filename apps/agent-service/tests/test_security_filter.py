"""Tests for guide-intelligence content-security filter."""

from datetime import UTC, datetime

import pytest

from trip_agent.guide_intelligence.security_filter import filter_content
from trip_agent.guide_intelligence.trusted_facts import CandidateFact


def _candidate(
    statement: str = "a normal fact",
    evidence: str = "page says this",
    category: str = "ATTRACTION_IDENTITY",
) -> CandidateFact:
    return CandidateFact(
        category=category,
        statement=statement,
        normalized_value={},
        evidence=evidence,
        evidence_start=0,
        evidence_end=len(evidence),
        confidence=0.9,
        checked_at=datetime(2026, 8, 5, tzinfo=UTC),
        expires_at=datetime(2026, 9, 5, tzinfo=UTC),
    )


# ── Positive cases (should pass) ────────────────────────────────────────

def test_normal_facts_pass() -> None:
    result = filter_content((
        _candidate("陈家祠是广州的文化景点"),
        _candidate("白云山门票5元", "官方页面显示票价"),
        _candidate("周一闭馆", "开放时间说明"),
    ))
    assert len(result.passed) == 3
    assert len(result.blocked) == 0


def test_legitimate_urls_pass() -> None:
    result = filter_content((
        _candidate("官网", "https://www.gz.gov.cn/visit"),
    ))
    assert len(result.passed) == 1
    assert len(result.blocked) == 0


# ── SQL injection ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "DROP TABLE users",
    "INSERT INTO admin VALUES (1, 'hack')",
    "DELETE FROM users WHERE 1=1",
    "UNION SELECT password FROM users",
    "UNION ALL SELECT * FROM admin",
    "UPDATE users SET role='admin'",
    "ALTER TABLE users ADD COLUMN backdoor TEXT",
    "TRUNCATE TABLE logs",
    "EXEC sp_executesql",
    "EXECUTE(sp_helptext)",
    "SELECT * FROM users",
    "SELECT @@version",
    "SELECT CURRENT_USER()",
    "SLEEP(10)",
    "' OR '1'='1",
    "' OR 1=1 --",
    "\" OR \"a\"=\"a",
])
def test_sql_injection_blocked(text: str) -> None:
    result = filter_content((_candidate(text),))
    assert len(result.passed) == 0
    assert len(result.blocked) == 1
    assert result.blocked[0].rule == "SECURITY_SQL_INJECTION"


# ── Script / HTML injection ─────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "<script>alert(1)</script>",
    "javascript:void(0)",
    "onerror=alert(1)",
    "onload=fetch('/steal')",
    "onclick=malicious()",
    "<iframe src='http://evil.com'>",
    "<embed src='malware.swf'>",
    "<object data='exploit'>",
    "<form action='http://evil.com'>",
])
def test_script_injection_blocked(text: str) -> None:
    result = filter_content((_candidate(text),))
    assert len(result.passed) == 0
    assert len(result.blocked) == 1
    assert result.blocked[0].rule == "SECURITY_SCRIPT_INJECTION"


def test_html_entity_injection_blocked() -> None:
    result = filter_content((_candidate("&#60;script&#62;"),))
    assert len(result.blocked) == 1
    assert result.blocked[0].rule == "SECURITY_SCRIPT_INJECTION"


# ── Suspicious URL ──────────────────────────────────────────────────────

def test_non_https_url_blocked() -> None:
    result = filter_content((
        _candidate("click here", "http://evil.com/phish"),
    ))
    assert len(result.blocked) == 1
    assert result.blocked[0].rule == "SECURITY_UNSAFE_URL"


def test_raw_ip_url_blocked() -> None:
    result = filter_content((
        _candidate("server", "https://192.168.1.1/admin"),
    ))
    assert len(result.blocked) == 1
    assert result.blocked[0].rule == "SECURITY_UNSAFE_URL"


@pytest.mark.parametrize("domain", [
    "bit.ly", "tinyurl.com", "t.co", "ow.ly", "is.gd",
    "buff.ly", "goo.gl", "shorte.st", "bc.vc", "adf.ly", "short.link",
])
def test_shortlink_url_blocked(domain: str) -> None:
    result = filter_content((
        _candidate("link", f"https://{domain}/abc123"),
    ))
    assert len(result.blocked) == 1, f"{domain} should be blocked"
    assert result.blocked[0].rule == "SECURITY_UNSAFE_URL"


# ── Control characters ──────────────────────────────────────────────────

def test_null_byte_blocked() -> None:
    result = filter_content((_candidate("normal\x00hidden"),))
    assert len(result.blocked) == 1
    assert result.blocked[0].rule == "SECURITY_CONTROL_CHARACTERS"


def test_vertical_tab_blocked() -> None:
    result = filter_content((_candidate("text\x0bmore"),))
    assert len(result.blocked) == 1


def test_bidi_override_blocked() -> None:
    result = filter_content((_candidate("safe‮-reversed"),))
    assert len(result.blocked) == 1
    assert result.blocked[0].rule == "SECURITY_CONTROL_CHARACTERS"


# ── Repetitive ──────────────────────────────────────────────────────────

def test_repetitive_content_blocked() -> None:
    result = filter_content((_candidate("A" * 250),))
    assert len(result.blocked) == 1
    assert result.blocked[0].rule == "SECURITY_REPETITIVE_CONTENT"


def test_near_limit_repetition_passes() -> None:
    result = filter_content((_candidate("A" * 150 + " normal text"),))
    assert len(result.passed) == 1


# ── Excessive length ────────────────────────────────────────────────────

def test_statement_too_long_blocked() -> None:
    long_text = "A tour of " + "the scenic spots and cultural heritage sites. " * 67
    assert len(long_text) > 2000
    result = filter_content((_candidate(statement=long_text),))
    assert len(result.blocked) == 1
    assert result.blocked[0].rule == "SECURITY_EXCESSIVE_LENGTH"


def test_evidence_too_long_blocked() -> None:
    long_ev = "Evidence: " + "according to official records and verified sources. " * 97
    assert len(long_ev) > 3000
    result = filter_content((_candidate(evidence=long_ev),))
    assert len(result.blocked) == 1
    assert result.blocked[0].rule == "SECURITY_EXCESSIVE_LENGTH"


def test_borderline_lengths_pass() -> None:
    result = filter_content((
        _candidate(
            statement="A short description",
            evidence="Brief evidence text",
        ),
    ))
    assert len(result.passed) == 1


# ── Mixed scenarios ─────────────────────────────────────────────────────

def test_security_blocked_facts_excluded_from_passed() -> None:
    result = filter_content((
        _candidate("normal fact 1"),
        _candidate("DROP TABLE users; -- hack"),
        _candidate("normal fact 2"),
        _candidate("<script>alert(1)</script>"),
        _candidate("normal fact 3"),
    ))
    assert len(result.passed) == 3
    assert len(result.blocked) == 2
    assert result.blocked[0].rule == "SECURITY_SQL_INJECTION"
    assert result.blocked[1].rule == "SECURITY_SCRIPT_INJECTION"


def test_first_violation_reported_when_multiple() -> None:
    result = filter_content((
        _candidate("DROP TABLE<script>alert(1)</script>http://evil.com\x00AAAA"),
    ))
    assert len(result.blocked) == 1
    # SQL injection is checked first, so it wins
    assert result.blocked[0].rule == "SECURITY_SQL_INJECTION"
