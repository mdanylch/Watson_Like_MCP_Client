from __future__ import annotations

from typing import Any

from app.codex_runner import invoke_codex_mcp_pipeline
from app.config import Settings


def _effective_org_user(
    settings: Settings,
    org_id: str | None,
    user_email: str | None,
) -> tuple[str | None, str | None]:
    """Request body overrides ORG_ID / USER_EMAIL from the environment."""
    oid = org_id if org_id is not None else settings.org_id
    em = user_email if user_email is not None else settings.user_email
    return oid, em


async def invoke_mcp_pipeline(
    settings: Settings,
    content: str,
    *,
    org_id: str | None = None,
    user_email: str | None = None,
) -> dict[str, Any]:
    """OAuth → Codex MCP config → ``codex exec`` (only execution path)."""
    oid, em = _effective_org_user(settings, org_id, user_email)
    return await invoke_codex_mcp_pipeline(settings, content, org_id=oid, user_email=em)
