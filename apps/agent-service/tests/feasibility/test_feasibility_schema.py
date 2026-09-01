"""B1-B/C — feasibility-report-v1 JSON Schema and shared fixtures (TDD).

Valid fixtures must pass the standalone schema; invalid fixtures must fail
at the documented layer (schema failure, semantic failure, or both).  The
semantic layer re-validates a parsed report with the Python model so forged
cross-field states are rejected on read.
"""

import json
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from trip_agent.feasibility.models import FeasibilityReport

_REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = _REPO_ROOT / "contracts" / "messaging" / "feasibility-report-v1.schema.json"
FIXTURE_DIR = _REPO_ROOT / "contracts" / "fixtures" / "feasibility-report-v1"

VALID_FIXTURES = (
    "verified",
    "needs-repair",
    "unverified-unknown",
    "unverified-missing-required",
    "opening-stale",
    "opening-conflicting",
    "opening-unknown",
    "opening-unknown-no-evidence",
)

# name -> expected failure layer(s)
INVALID_FIXTURES = {
    "forged-verified-unknown": {"semantic"},
    "forged-verified-missing-required": {"semantic"},
    "forged-verified-fail": {"semantic"},
    "summary-mismatch": {"semantic"},
    "duplicate-rule-id": {"semantic"},
    "naive-validated-at": {"semantic"},
    "invalid-status-enum": {"schema"},
    "invalid-outcome-enum": {"schema"},
    "bad-fingerprint": {"schema"},
    "too-many-repair-attempts": {"schema"},
    "repair-index-gap": {"semantic"},
    "stale-eligible": {"semantic"},
    "conflicting-eligible": {"semantic"},
    "opening-pass-stale": {"semantic"},
    "opening-pass-no-eligible": {"semantic"},
    "opening-pass-no-evidence": {"semantic"},
    "opening-fail-no-evidence": {"semantic"},
    "opening-pass-wrong-evidence-type": {"semantic"},
    "invalid-schema-version": {"schema"},
    "additional-property": {"schema"},
}


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


# ── schema shape ───────────────────────────────────────────────────────────


def test_schema_is_standalone_and_version_one() -> None:
    schema = _load_schema()
    assert schema["$id"].endswith("feasibility-report-v1.schema.json")
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schemaVersion"]["const"] == 1


def test_schema_rejects_additional_properties_in_objects() -> None:
    schema = _load_schema()
    assert schema["$defs"]["ruleResult"]["additionalProperties"] is False
    assert schema["$defs"]["evidenceReference"]["additionalProperties"] is False
    assert schema["$defs"]["repairAttempt"]["additionalProperties"] is False
    assert schema["properties"]["summary"]["additionalProperties"] is False


# ── valid fixtures ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", VALID_FIXTURES)
def test_valid_fixture_passes_schema(name: str) -> None:
    Draft202012Validator(_load_schema()).validate(_load_fixture(name))


@pytest.mark.parametrize("name", VALID_FIXTURES)
def test_valid_fixture_parses_as_python_model(name: str) -> None:
    report = FeasibilityReport.model_validate(_load_fixture(name))
    assert report.schema_version == 1


# ── invalid fixtures ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "layers"),
    [(name, layers) for name, layers in INVALID_FIXTURES.items()],
)
def test_invalid_fixture_fails_at_documented_layer(name: str, layers: set[str]) -> None:
    instance = _load_fixture(name)
    schema_errors: list[Exception] = []
    try:
        Draft202012Validator(_load_schema()).validate(instance)
    except jsonschema.ValidationError as error:
        schema_errors.append(error)

    if "schema" in layers:
        assert schema_errors, f"{name} should fail at the schema layer"
    if "semantic" in layers:
        assert not schema_errors, f"{name} should pass schema to reach semantic layer"
        with pytest.raises(ValidationError):
            FeasibilityReport.model_validate(instance)
