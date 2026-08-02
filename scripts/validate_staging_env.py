from __future__ import annotations

import argparse
import ipaddress
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path


_SECRET_MINIMUM_LENGTHS = {
    "POSTGRES_PASSWORD": 16,
    "REDIS_PASSWORD": 16,
    "RABBITMQ_PASSWORD": 16,
    "JWT_SECRET": 32,
    "AGENT_INTERNAL_TOKEN": 32,
    "INTERNAL_DIAGNOSTICS_TOKEN": 32,
    "AMAP_WEB_SERVICE_KEY": 8,
    "QWEATHER_API_KEY": 8,
    "VITE_AMAP_WEB_JS_KEY": 8,
    "VITE_AMAP_SECURITY_CODE": 8,
}
_PLACEHOLDER_MARKERS = (
    "replace-with",
    "change-me",
    "changeme",
    "your-secret",
    "your-key",
    "example-key",
)
_HOST_PATTERN = re.compile(
    r"(?=.{4,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z",
    re.IGNORECASE,
)
_INTERPOLATION_PATTERN = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[^}]+\})")
_IMMUTABLE_IMAGE_VARIABLES = (
    "POSTGRES_IMAGE",
    "REDIS_IMAGE",
    "RABBITMQ_IMAGE",
    "TRAVEL_SERVER_IMAGE",
    "AGENT_SERVICE_IMAGE",
    "WEB_IMAGE",
    "PROMETHEUS_IMAGE",
)
_DIGEST_IMAGE_PATTERN = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}\Z", re.IGNORECASE)


def _decode_double_quoted(value: str) -> str:
    replacements = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 1 < len(value):
            escaped = value[index + 1]
            result.append(replacements.get(escaped, f"\\{escaped}"))
            index += 2
            continue
        result.append(value[index])
        index += 1
    return "".join(result)


def _parse_env_value(raw_value: str, line_number: int) -> str:
    value = raw_value.strip()
    if not value or value[0] not in {'"', "'"}:
        inline_comment = re.search(r"\s+#", value)
        return value[: inline_comment.start()].rstrip() if inline_comment else value

    quote = value[0]
    escaped = False
    closing_index: int | None = None
    for index, character in enumerate(value[1:], 1):
        if quote == '"' and character == "\\" and not escaped:
            escaped = True
            continue
        if character == quote and not escaped:
            closing_index = index
            break
        escaped = False
    if closing_index is None:
        raise ValueError(f"line {line_number} has an unterminated quoted value")
    trailing = value[closing_index + 1 :].strip()
    if trailing and not trailing.startswith("#"):
        raise ValueError(f"line {line_number} has text after a quoted value")
    content = value[1:closing_index]
    return _decode_double_quoted(content) if quote == '"' else content


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            raise ValueError(f"line {line_number} is not a KEY=VALUE assignment")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
            raise ValueError(f"line {line_number} has an invalid variable name")
        values[key] = _parse_env_value(value, line_number)
    return values


def _required_value(values: Mapping[str, str], name: str, errors: list[str]) -> str:
    value = values.get(name, "").strip()
    if not value:
        errors.append(f"{name} must be configured")
    return value


def _validate_secret(
    values: Mapping[str, str],
    name: str,
    minimum_length: int,
    errors: list[str],
) -> str:
    value = _required_value(values, name, errors)
    if value and len(value.encode("utf-8")) < minimum_length:
        errors.append(f"{name} must contain at least {minimum_length} UTF-8 bytes")
    lowered = value.lower()
    if value and any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        errors.append(f"{name} must not use a documented placeholder")
    if value and _INTERPOLATION_PATTERN.search(value):
        errors.append(f"{name} must not use variable interpolation")
    return value


def _validate_qweather_host(host: str, errors: list[str]) -> None:
    lowered = host.lower().rstrip(".")
    if (
        not _HOST_PATTERN.fullmatch(lowered)
        or "://" in host
        or "/" in host
        or lowered in {"localhost", "api.qweather.com"}
        or lowered.endswith((".example.com", ".example", ".invalid", ".test"))
    ):
        errors.append(
            "QWEATHER_API_HOST must be the dedicated hostname assigned in QWeather Console"
        )


def _validate_proxy_cidr(value: str, errors: list[str]) -> None:
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError:
        errors.append("TRUSTED_PROXY_CIDR must be a valid CIDR")
        return
    if network.num_addresses > 256:
        errors.append("TRUSTED_PROXY_CIDR must not trust more than 256 addresses")


def validate_staging_environment(values: Mapping[str, str]) -> list[str]:
    errors: list[str] = []

    app_env = _required_value(values, "APP_ENV", errors)
    if app_env and app_env not in {"staging", "production"}:
        errors.append("APP_ENV must be staging or production")

    image_tag = _required_value(values, "IMAGE_TAG", errors)
    if image_tag.lower() in {"local", "latest"}:
        errors.append("IMAGE_TAG must identify the reviewed candidate, not local/latest")
    for image_variable in _IMMUTABLE_IMAGE_VARIABLES:
        image_reference = _required_value(values, image_variable, errors)
        if image_reference and not _DIGEST_IMAGE_PATTERN.fullmatch(image_reference):
            errors.append(f"{image_variable} must use a complete @sha256 digest reference")

    provider_mode = _required_value(values, "PROVIDER_MODE", errors)
    if provider_mode and provider_mode != "REAL_ONLY":
        errors.append("PROVIDER_MODE must be REAL_ONLY for staging acceptance")
    demo_mode = values.get("DEMO_MODE", "").strip().lower()
    if demo_mode not in {"", "false"}:
        errors.append("DEMO_MODE must be absent or false when PROVIDER_MODE=REAL_ONLY")

    fallback_categories = values.get("PROVIDER_FALLBACK_CATEGORIES", "")
    try:
        parsed_fallback = json.loads(fallback_categories)
    except json.JSONDecodeError:
        parsed_fallback = None
    if parsed_fallback != []:
        errors.append("PROVIDER_FALLBACK_CATEGORIES must be [] for staging acceptance")

    secrets = {
        name: _validate_secret(values, name, minimum, errors)
        for name, minimum in _SECRET_MINIMUM_LENGTHS.items()
    }
    private_secret_names = (
        "JWT_SECRET",
        "AGENT_INTERNAL_TOKEN",
        "INTERNAL_DIAGNOSTICS_TOKEN",
    )
    private_values = [secrets[name] for name in private_secret_names if secrets[name]]
    if len(private_values) != len(set(private_values)):
        errors.append(
            "JWT_SECRET, AGENT_INTERNAL_TOKEN, and INTERNAL_DIAGNOSTICS_TOKEN must be distinct"
        )
    browser_secret_names = ("VITE_AMAP_WEB_JS_KEY", "VITE_AMAP_SECURITY_CODE")
    server_secret_names = tuple(
        name for name in _SECRET_MINIMUM_LENGTHS if name not in browser_secret_names
    )
    for server_name in server_secret_names:
        for browser_name in browser_secret_names:
            if secrets[server_name] and secrets[server_name] == secrets[browser_name]:
                errors.append(f"{server_name} and {browser_name} must be distinct")
    if (
        secrets["VITE_AMAP_WEB_JS_KEY"]
        and secrets["VITE_AMAP_WEB_JS_KEY"] == secrets["VITE_AMAP_SECURITY_CODE"]
    ):
        errors.append("VITE_AMAP_WEB_JS_KEY and VITE_AMAP_SECURITY_CODE must be distinct")

    qweather_host = _required_value(values, "QWEATHER_API_HOST", errors)
    if qweather_host:
        _validate_qweather_host(qweather_host, errors)

    if values.get("REFRESH_COOKIE_SECURE", "").strip().lower() != "true":
        errors.append("REFRESH_COOKIE_SECURE must be true")

    proxy_cidr = _required_value(values, "TRUSTED_PROXY_CIDR", errors)
    if proxy_cidr:
        _validate_proxy_cidr(proxy_cidr, errors)

    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a TripPilot staging environment without printing secrets."
    )
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        values = load_env(args.env_file)
    except (OSError, ValueError) as error:
        print(f"staging preflight failed: {error}")
        return 2

    errors = validate_staging_environment(values)
    if errors:
        print(f"staging preflight failed with {len(errors)} issue(s):")
        for error in errors:
            print(f"- {error}")
        return 1
    print("staging preflight passed; no secret values were printed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
