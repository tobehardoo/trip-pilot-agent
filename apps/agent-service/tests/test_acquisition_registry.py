import json
from pathlib import Path

import pytest

from trip_agent.acquisition.cli import main
from trip_agent.acquisition.discovery import StaticUrlDiscoverer
from trip_agent.acquisition.models import KnowledgeSource
from trip_agent.acquisition.registry import SourceCatalog, SourceConfigurationError
from trip_agent.acquisition.security import SourceSecurityError, validate_source_url

KNOWLEDGE_ROOT = Path(__file__).parents[3] / "knowledge"


def test_source_catalog_loads_official_guangzhou_sources() -> None:
    catalog = SourceCatalog.load_directory(KNOWLEDGE_ROOT / "sources")

    sources = catalog.for_city("广州")

    assert len(sources) == 1
    assert sources[0].source_id == "guangzhou-government-tourism"
    assert len(sources[0].resource_urls) == 3
    assert sources[0].allowed_domains == ("www.gz.gov.cn",)
    assert sources[0].min_request_interval_seconds == 1.0
    assert isinstance(sources[0].min_request_interval_seconds, float)


def test_static_discoverer_emits_typed_resources() -> None:
    source = SourceCatalog.load_directory(KNOWLEDGE_ROOT / "sources").for_city("广州")[0]

    resources = StaticUrlDiscoverer().discover(source)

    assert tuple(resource.url for resource in resources) == source.resource_urls
    assert all(resource.source_id == source.source_id for resource in resources)
    assert all(resource.city == "广州" for resource in resources)


def test_source_catalog_rejects_duplicate_source_ids(tmp_path: Path) -> None:
    source = """
[[sources]]
source_id = "duplicate"
city = "广州"
source_name = "测试来源"
reliability_level = "CURATED"
allowed_domains = ["example.com"]
resource_urls = ["https://example.com/article"]
"""
    (tmp_path / "one.toml").write_text(source, encoding="utf-8")
    (tmp_path / "two.toml").write_text(source, encoding="utf-8")

    with pytest.raises(SourceConfigurationError, match="duplicate source_id"):
        SourceCatalog.load_directory(tmp_path)


def test_source_catalog_rejects_duplicate_resource_urls_across_sources(tmp_path: Path) -> None:
    source = """
[[sources]]
source_id = "one"
city = "广州"
source_name = "来源一"
reliability_level = "CURATED"
allowed_domains = ["example.com"]
resource_urls = ["https://example.com/article"]
"""
    second = source.replace('source_id = "one"', 'source_id = "two"').replace("来源一", "来源二")
    (tmp_path / "one.toml").write_text(source, encoding="utf-8")
    (tmp_path / "two.toml").write_text(second, encoding="utf-8")

    with pytest.raises(SourceConfigurationError, match="duplicate resource URL"):
        SourceCatalog.load_directory(tmp_path)


@pytest.mark.parametrize(
    ("url", "domains", "message"),
    [
        ("http://example.com/article", ("example.com",), "https"),
        ("https://user:pass@example.com/article", ("example.com",), "credentials"),
        ("https://192.168.1.20/article", ("192.168.1.20",), "public address"),
        ("https://localhost/article", ("localhost",), "localhost"),
        ("https://2130706433/article", ("2130706433",), "numeric-only"),
        ("https://outside.example/article", ("example.com",), "allowed domain"),
    ],
)
def test_source_url_policy_rejects_unsafe_urls(
    url: str,
    domains: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(SourceSecurityError, match=message):
        validate_source_url(url, allowed_domains=domains)


def test_source_model_rejects_resource_outside_allowed_domain() -> None:
    with pytest.raises(SourceSecurityError, match="allowed domain"):
        KnowledgeSource(
            source_id="guangzhou-official",
            city="广州",
            source_name="官方来源",
            reliability_level="OFFICIAL",
            allowed_domains=("www.gz.gov.cn",),
            resource_urls=("https://example.com/not-allowed",),
        )


def test_source_model_rejects_duplicate_resource_urls() -> None:
    with pytest.raises(ValueError, match="resource_urls must be non-empty and unique"):
        KnowledgeSource(
            source_id="duplicate-resource",
            city="广州",
            source_name="测试来源",
            reliability_level="CURATED",
            allowed_domains=("example.com",),
            resource_urls=("https://example.com/article", "https://example.com/article"),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("fetch_interval_hours", 0, "fetch_interval_hours"),
        ("fetch_interval_hours", 8761, "fetch_interval_hours"),
        ("min_request_interval_seconds", 0, "min_request_interval_seconds"),
        ("request_timeout_seconds", 0, "request_timeout_seconds"),
        ("max_response_bytes", 1024, "max_response_bytes"),
    ],
)
def test_source_model_rejects_invalid_fetch_policy_bounds(
    field: str,
    value: int,
    message: str,
) -> None:
    kwargs = {
        "source_id": "bounded-source",
        "city": "广州",
        "source_name": "测试来源",
        "reliability_level": "CURATED",
        "allowed_domains": ("example.com",),
        "resource_urls": ("https://example.com/article",),
        field: value,
    }

    with pytest.raises(ValueError, match=message):
        KnowledgeSource(**kwargs)


def test_source_catalog_rejects_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(SourceConfigurationError, match="no TOML"):
        SourceCatalog.load_directory(tmp_path)


def test_source_catalog_adds_file_context_to_unsafe_urls(tmp_path: Path) -> None:
    (tmp_path / "unsafe.toml").write_text(
        """
[[sources]]
source_id = "unsafe"
city = "广州"
source_name = "不安全来源"
reliability_level = "CURATED"
allowed_domains = ["example.com"]
resource_urls = ["http://example.com/article"]
""",
        encoding="utf-8",
    )

    with pytest.raises(SourceConfigurationError, match=r"unsafe\.toml.*https"):
        SourceCatalog.load_directory(tmp_path)


def test_cli_validate_returns_json_error_for_malformed_toml_types(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "malformed.toml").write_text(
        """
[[sources]]
source_id = 123
city = "广州"
source_name = "错误来源"
reliability_level = "CURATED"
allowed_domains = [123]
resource_urls = ["https://example.com/article"]
""",
        encoding="utf-8",
    )

    assert main(["validate", str(tmp_path)]) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure["status"] == "error"
    assert "malformed.toml" in failure["message"]


def test_cli_validate_reports_counts_and_configuration_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["validate", str(KNOWLEDGE_ROOT / "sources")]) == 0
    success = json.loads(capsys.readouterr().out)
    assert success == {"resource_count": 3, "source_count": 1, "status": "valid"}

    assert main(["validate", str(tmp_path)]) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure["status"] == "error"
    assert "no TOML" in failure["message"]
