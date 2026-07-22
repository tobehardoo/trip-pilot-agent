"""Immutable source and discovery models for knowledge acquisition."""

import re
from dataclasses import dataclass
from typing import Literal

from trip_agent.acquisition.security import normalize_allowed_domain, validate_source_url

type ReliabilityLevel = Literal["OFFICIAL", "CURATED", "COMMUNITY"]

_SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    source_id: str
    city: str
    source_name: str
    reliability_level: ReliabilityLevel
    allowed_domains: tuple[str, ...]
    resource_urls: tuple[str, ...]
    fetch_interval_hours: int = 168
    min_request_interval_seconds: float = 1.0
    request_timeout_seconds: float = 10.0
    max_response_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        source_id = _require_text(self.source_id, "source_id")
        city = _require_text(self.city, "city")
        source_name = _require_text(self.source_name, "source_name")
        if not _SOURCE_ID_PATTERN.fullmatch(source_id):
            raise ValueError("source_id must be lowercase kebab-case")
        if not isinstance(self.reliability_level, str) or self.reliability_level not in {
            "OFFICIAL",
            "CURATED",
            "COMMUNITY",
        }:
            raise ValueError(f"unsupported reliability level: {self.reliability_level}")
        if not isinstance(self.fetch_interval_hours, int) or isinstance(
            self.fetch_interval_hours, bool
        ) or self.fetch_interval_hours < 1:
            raise ValueError("fetch_interval_hours must be positive")
        if not isinstance(self.min_request_interval_seconds, int | float) or isinstance(
            self.min_request_interval_seconds, bool
        ) or not 0.1 <= self.min_request_interval_seconds <= 60:
            raise ValueError("min_request_interval_seconds must be between 0.1 and 60")
        if not isinstance(self.request_timeout_seconds, int | float) or isinstance(
            self.request_timeout_seconds, bool
        ) or not 0 < self.request_timeout_seconds <= 60:
            raise ValueError("request_timeout_seconds must be between zero and 60")
        if not isinstance(self.max_response_bytes, int) or isinstance(
            self.max_response_bytes, bool
        ) or not 64 * 1024 <= self.max_response_bytes <= 10 * 1024 * 1024:
            raise ValueError("max_response_bytes must be between 64 KiB and 10 MiB")

        if not isinstance(self.allowed_domains, list | tuple):
            raise ValueError("allowed_domains must be a list or tuple of strings")
        if not isinstance(self.resource_urls, list | tuple):
            raise ValueError("resource_urls must be a list or tuple of strings")
        domains = tuple(
            normalize_allowed_domain(_require_text(domain, "allowed_domain"))
            for domain in self.allowed_domains
        )
        if not domains or len(domains) != len(set(domains)):
            raise ValueError("allowed_domains must be non-empty and unique")
        urls = tuple(
            validate_source_url(_require_text(url, "resource_url"), allowed_domains=domains)
            for url in self.resource_urls
        )
        if not urls or len(urls) != len(set(urls)):
            raise ValueError("resource_urls must be non-empty and unique")
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "city", city)
        object.__setattr__(self, "source_name", source_name)
        object.__setattr__(self, "allowed_domains", domains)
        object.__setattr__(self, "resource_urls", urls)
        object.__setattr__(
            self,
            "min_request_interval_seconds",
            float(self.min_request_interval_seconds),
        )


@dataclass(frozen=True, slots=True)
class DiscoveredResource:
    source_id: str
    city: str
    url: str


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized
