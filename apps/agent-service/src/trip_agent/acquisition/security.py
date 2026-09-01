"""URL policy checks shared by source configuration and future fetchers."""

import ipaddress
from urllib.parse import SplitResult, urlsplit, urlunsplit


class SourceSecurityError(ValueError):
    """Raised when a configured source URL violates the acquisition policy."""


def normalize_allowed_domain(value: str) -> str:
    candidate = value.strip().lower().rstrip(".")
    if not candidate or "/" in candidate or ":" in candidate or "@" in candidate:
        raise SourceSecurityError(f"invalid allowed domain: {value}")
    try:
        return candidate.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise SourceSecurityError(f"invalid allowed domain: {value}") from error


def validate_source_url(url: str, *, allowed_domains: tuple[str, ...]) -> str:
    parsed = urlsplit(url.strip())
    _require_https(parsed, url)
    if parsed.username is not None or parsed.password is not None:
        raise SourceSecurityError("source URL cannot contain credentials")
    try:
        port = parsed.port
    except ValueError as error:
        raise SourceSecurityError("source URL has an invalid port") from error
    if port not in (None, 443):
        raise SourceSecurityError("source URL must use the default HTTPS port")

    hostname = parsed.hostname
    if not hostname:
        raise SourceSecurityError("source URL must contain a hostname")
    normalized_host = hostname.encode("idna").decode("ascii").lower().rstrip(".")
    if normalized_host == "localhost":
        raise SourceSecurityError("source URL host cannot be localhost")
    if normalized_host.isdigit():
        raise SourceSecurityError("source URL host cannot be numeric-only")
    _require_public_ip_if_literal(normalized_host)
    domains = tuple(normalize_allowed_domain(domain) for domain in allowed_domains)
    if not any(
        normalized_host == domain or normalized_host.endswith(f".{domain}") for domain in domains
    ):
        raise SourceSecurityError(f"source URL host is outside the allowed domain: {hostname}")
    return urlunsplit(("https", normalized_host, parsed.path or "/", parsed.query, ""))


def _require_https(parsed: SplitResult, original_url: str) -> None:
    if parsed.scheme.casefold() != "https":
        raise SourceSecurityError(f"source URL must use https: {original_url}")


def _require_public_ip_if_literal(hostname: str) -> None:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not address.is_global:
        raise SourceSecurityError("source URL host must be a public address")
