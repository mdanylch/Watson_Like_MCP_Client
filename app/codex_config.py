from __future__ import annotations

from pathlib import Path
from typing import Any

import tomli_w

from app.config import Settings


def write_codex_mcp_config(
    codex_home: Path,
    settings: Settings,
    *,
    org_id: str | None,
    user_email: str | None,
) -> str:
    """
    Write ~/.codex/config.toml under codex_home so `codex exec` can reach BDB via streamable HTTP.

    See: https://developers.openai.com/codex/mcp (bearer_token_env_var, env_http_headers).
    """
    cfg_dir = codex_home / ".codex"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    server: dict[str, Any] = {
        "url": settings.mcp_base_url.strip(),
        "bearer_token_env_var": "BDB_MCP_BEARER_TOKEN",
        "required": True,
        "enabled": True,
    }

    env_headers: dict[str, str] = {}
    oid = org_id if org_id is not None else settings.org_id
    em = user_email if user_email is not None else settings.user_email
    if oid:
        env_headers["X-Org-Id"] = "BDB_ORG_ID"
    if em:
        env_headers["X-User-Email"] = "BDB_USER_EMAIL"
    if env_headers:
        server["env_http_headers"] = env_headers

    doc: dict[str, Any] = {
        "mcp_servers": {settings.codex_mcp_server_name: server},
    }

    path = cfg_dir / "config.toml"
    path.write_text(tomli_w.dumps(doc), encoding="utf-8")
    return str(path)
