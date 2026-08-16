"""Shared internal-service token guard for agent-api endpoints."""

import hmac
import os

from fastapi import HTTPException, status


def require_internal_token(provided: str | None) -> None:
    """Reject requests that do not carry the configured internal token.

    The token lives only in the server environment (``AGENT_INTERNAL_TOKEN``)
    and is never logged or echoed; comparison is constant-time.
    """
    expected = os.getenv("AGENT_INTERNAL_TOKEN", "")
    if not expected or provided is None or not hmac.compare_digest(provided, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal service token")
