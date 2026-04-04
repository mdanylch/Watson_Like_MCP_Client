from __future__ import annotations

from app.config import Settings


def httpx_verify(settings: Settings) -> bool | str:
    """What to pass to httpx ``verify=`` (bool or path to PEM bundle)."""
    if not settings.http_ssl_verify:
        return False
    if settings.ssl_ca_bundle:
        return settings.ssl_ca_bundle
    return True
