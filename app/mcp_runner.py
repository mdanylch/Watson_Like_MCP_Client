from __future__ import annotations

from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult

from app.bdb_oauth import fetch_client_credentials_token
from app.codex_runner import invoke_codex_mcp_pipeline
from app.config import Settings
from app.llm_router import choose_tool_calls, summarize_tool_results
from app.mcp_tools import mcp_tools_to_openai_functions, tool_result_to_serializable


class BearerAuth(httpx.Auth):
    """Attach Bearer token to every request (MCP streamable HTTP)."""

    def __init__(self, token: str) -> None:
        self.token = token

    def auth_flow(self, request: httpx.Request):
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


def _extra_headers(
    settings: Settings,
    org_id: str | None = None,
    user_email: str | None = None,
) -> dict[str, str]:
    h: dict[str, str] = {}
    oid = org_id if org_id is not None else settings.org_id
    em = user_email if user_email is not None else settings.user_email
    if oid:
        h["X-Org-Id"] = oid
    if em:
        h["X-User-Email"] = em
    return h


async def invoke_mcp_pipeline(
    settings: Settings,
    content: str,
    *,
    org_id: str | None = None,
    user_email: str | None = None,
) -> dict[str, Any]:
    if settings.router_mode == "codex_cli":
        return await invoke_codex_mcp_pipeline(
            settings,
            content,
            org_id=org_id,
            user_email=user_email,
        )

    return await invoke_openai_mcp_pipeline(
        settings,
        content,
        org_id=org_id,
        user_email=user_email,
    )


async def invoke_openai_mcp_pipeline(
    settings: Settings,
    content: str,
    *,
    org_id: str | None = None,
    user_email: str | None = None,
) -> dict[str, Any]:
    """
    Fallback: Python MCP SDK + OpenAI function calling (no Codex CLI).
    """
    token = await fetch_client_credentials_token(settings)
    url = settings.mcp_base_url.strip()
    auth = BearerAuth(token)
    extra = _extra_headers(settings, org_id=org_id, user_email=user_email)

    async with streamablehttp_client(url, headers=extra or None, auth=auth) as streams:
        read, write, _ = streams
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            tools = list(listed.tools)
            if not tools:
                raise RuntimeError("MCP server returned no tools")

            openai_tools = mcp_tools_to_openai_functions(tools)
            planned = await choose_tool_calls(settings, content, openai_tools)

            results_serial: list[dict[str, Any]] = []
            for call in planned:
                name = call["name"]
                arguments = call.get("arguments") or {}
                raw: CallToolResult = await session.call_tool(name, arguments)
                results_serial.append(
                    {
                        "tool": name,
                        "arguments": arguments,
                        "result": tool_result_to_serializable(raw),
                    }
                )

            summary: str | None = None
            if settings.assistant_followup:
                summary = await summarize_tool_results(settings, content, results_serial)

            return {
                "mode": "openai_api",
                "tools_available": len(tools),
                "planned_calls": planned,
                "results": results_serial,
                "assistant_summary": summary,
            }
