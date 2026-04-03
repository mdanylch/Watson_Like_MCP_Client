from __future__ import annotations

import httpx

from app.config import Settings


async def fetch_client_credentials_token(settings: Settings) -> str:
    """OAuth 2.0 client_credentials token for BDB (Duo SSO)."""
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.client_id_bdb,
        "client_secret": settings.client_secret_bdb,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            settings.bdb_token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        payload = r.json()
    token = payload.get("access_token")
    if not token or not isinstance(token, str):
        raise RuntimeError("Token response missing access_token")
    return token
