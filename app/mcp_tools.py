from __future__ import annotations

import json
from typing import Any

from mcp.types import CallToolResult


def mcp_tools_to_openai_functions(tools: list[Any]) -> list[dict[str, Any]]:
    """Map MCP tool definitions to OpenAI Chat Completions `tools` format."""
    out: list[dict[str, Any]] = []
    for t in tools:
        if hasattr(t, "name"):
            name = t.name
            desc = t.description or ""
            schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None)
        elif isinstance(t, dict):
            name = t.get("name")
            desc = t.get("description") or ""
            schema = t.get("inputSchema")
        else:
            continue
        if not name:
            continue
        params = schema if isinstance(schema, dict) else {"type": "object", "properties": {}}
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc[:8000] if isinstance(desc, str) else "",
                    "parameters": params,
                },
            }
        )
    return out


def tool_result_to_serializable(result: CallToolResult) -> dict[str, Any]:
    """Convert MCP CallToolResult to JSON-friendly dict."""
    return result.model_dump(mode="json")


def safe_json_loads_arguments(raw: str) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {"value": val}
    except json.JSONDecodeError:
        return {"_raw": raw}
