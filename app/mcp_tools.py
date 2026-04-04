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


def _input_schema_for_tool(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)
    return schema if isinstance(schema, dict) else {}


def inject_session_context_into_planned_calls(
    planned: list[dict[str, Any]],
    tools: list[Any],
    org_id: str | None,
    user_email: str | None,
) -> list[dict[str, Any]]:
    """
    Merge org_id / user_email from the HTTP request into each tool call when the MCP
    tool schema expects those parameters but the router returned empty or partial args.
    Headers (X-Org-Id) are not passed automatically to call_tool — arguments must carry them.
    """
    by_name = {getattr(t, "name", None): t for t in tools if getattr(t, "name", None)}

    org_aliases = ("org_id", "organization_id", "organizationId", "orgId")
    email_aliases = ("user_email", "userEmail", "email")

    out: list[dict[str, Any]] = []
    for call in planned:
        name = call["name"]
        args = dict(call.get("arguments") or {})
        tool = by_name.get(name)
        schema = _input_schema_for_tool(tool) if tool is not None else {}
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        prop_keys = set(props.keys()) if props else set()
        required = schema.get("required") if isinstance(schema.get("required"), list) else []

        def empty(v: Any) -> bool:
            return v is None or v == ""

        if org_id:
            matched = False
            for key in org_aliases:
                if key in prop_keys or key in required:
                    if empty(args.get(key)):
                        args[key] = org_id
                    matched = True
                    break
            if not matched and not prop_keys and not required:
                args.setdefault("org_id", org_id)
            elif not matched and prop_keys:
                for key in org_aliases:
                    if key in prop_keys and empty(args.get(key)):
                        args[key] = org_id
                        matched = True
                        break

        if user_email:
            matched = False
            for key in email_aliases:
                if key in prop_keys or key in required:
                    if empty(args.get(key)):
                        args[key] = user_email
                    matched = True
                    break
            if not matched and not prop_keys and not required:
                args.setdefault("user_email", user_email)
            elif not matched and prop_keys:
                for key in email_aliases:
                    if key in prop_keys and empty(args.get(key)):
                        args[key] = user_email
                        matched = True
                        break

        out.append({"name": name, "arguments": args})
    return out
