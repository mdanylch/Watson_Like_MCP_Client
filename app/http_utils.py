from __future__ import annotations

from typing import Any

import httpx
from mcp.shared._httpx_utils import MCP_DEFAULT_SSE_READ_TIMEOUT, MCP_DEFAULT_TIMEOUT

from app.config import Settings


def httpx_verify(settings: Settings) -> bool | str:
    """What to pass to httpx/OpenAI ``verify=`` (bool or path to PEM bundle)."""
    if not settings.http_ssl_verify:
        return False
    if settings.ssl_ca_bundle:
        return settings.ssl_ca_bundle
    return True


def mcp_httpx_client_factory(settings: Settings):
    """Factory for ``streamablehttp_client(..., httpx_client_factory=...)`` with TLS options."""

    verify = httpx_verify(settings)

    def _factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "follow_redirects": True,
            "verify": verify,
        }
        if timeout is None:
            kwargs["timeout"] = httpx.Timeout(MCP_DEFAULT_TIMEOUT, read=MCP_DEFAULT_SSE_READ_TIMEOUT)
        else:
            kwargs["timeout"] = timeout
        if headers is not None:
            kwargs["headers"] = headers
        if auth is not None:
            kwargs["auth"] = auth
        return httpx.AsyncClient(**kwargs)

    return _factory


