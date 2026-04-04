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


def _collect_schema_property_keys(schema: dict[str, Any], depth: int = 0) -> set[str]:
    """Collect `properties` keys at all nested levels (JSON Schema)."""
    if depth > 12:
        return set()
    out: set[str] = set()
    props = schema.get("properties")
    if isinstance(props, dict):
        for key, sub in props.items():
            out.add(key)
            if isinstance(sub, dict):
                out |= _collect_schema_property_keys(sub, depth + 1)
    for combo in ("allOf", "anyOf", "oneOf"):
        block = schema.get(combo)
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict):
                    out |= _collect_schema_property_keys(item, depth + 1)
    return out


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

    def empty(v: Any) -> bool:
        return v is None or v == ""

    def any_org_set(d: dict[str, Any]) -> bool:
        return any(not empty(d.get(k)) for k in org_aliases)

    def any_email_set(d: dict[str, Any]) -> bool:
        return any(not empty(d.get(k)) for k in email_aliases)

    def merge_org_fallback(args_dict: dict[str, Any], value: str, schema: dict[str, Any]) -> None:
        """Fill org_id when schema omits it, or when it lives under input/params/etc."""
        if any_org_set(args_dict):
            return
        top_props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for container in ("input", "params", "body", "data", "kwargs", "query", "arguments"):
            if container not in top_props:
                continue
            sub_schema = top_props[container]
            if not isinstance(sub_schema, dict):
                continue
            nested_keys = _collect_schema_property_keys(sub_schema)
            if not nested_keys or not any(k in nested_keys for k in org_aliases):
                continue
            sub = args_dict.get(container)
            if not isinstance(sub, dict):
                sub = {}
            for k in org_aliases:
                if k in nested_keys and empty(sub.get(k)):
                    sub[k] = value
                    args_dict[container] = sub
                    return
            sub.setdefault("org_id", value)
            args_dict[container] = sub
            return
        for container in ("input", "params", "body", "data", "kwargs", "query", "arguments"):
            sub = args_dict.get(container)
            if isinstance(sub, dict) and not any_org_set(sub):
                sub.setdefault("org_id", value)
                args_dict[container] = sub
                return
        args_dict.setdefault("org_id", value)

    def merge_email_fallback(args_dict: dict[str, Any], value: str, schema: dict[str, Any]) -> None:
        if any_email_set(args_dict):
            return
        top_props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for container in ("input", "params", "body", "data", "kwargs", "query", "arguments"):
            if container not in top_props:
                continue
            sub_schema = top_props[container]
            if not isinstance(sub_schema, dict):
                continue
            nested_keys = _collect_schema_property_keys(sub_schema)
            if not nested_keys or not any(k in nested_keys for k in email_aliases):
                continue
            sub = args_dict.get(container)
            if not isinstance(sub, dict):
                sub = {}
            for k in email_aliases:
                if k in nested_keys and empty(sub.get(k)):
                    sub[k] = value
                    args_dict[container] = sub
                    return
            sub.setdefault("user_email", value)
            args_dict[container] = sub
            return
        for container in ("input", "params", "body", "data", "kwargs", "query", "arguments"):
            sub = args_dict.get(container)
            if isinstance(sub, dict) and not any_email_set(sub):
                sub.setdefault("user_email", value)
                args_dict[container] = sub
                return
        args_dict.setdefault("user_email", value)

    out: list[dict[str, Any]] = []
    for call in planned:
        name = call["name"]
        args = dict(call.get("arguments") or {})
        tool = by_name.get(name)
        schema = _input_schema_for_tool(tool) if tool is not None else {}
        top_props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        top_keys = set(top_props.keys()) if top_props else set()
        required = schema.get("required") if isinstance(schema.get("required"), list) else []

        if org_id:
            matched = False
            for key in org_aliases:
                if key in top_keys or key in required:
                    if empty(args.get(key)):
                        args[key] = org_id
                    matched = True
                    break
            if not matched and not top_keys and not required:
                args.setdefault("org_id", org_id)
            elif not matched and top_keys:
                for key in org_aliases:
                    if key in top_keys and empty(args.get(key)):
                        args[key] = org_id
                        matched = True
                        break
            if org_id and not any_org_set(args):
                merge_org_fallback(args, org_id, schema)

        if user_email:
            matched = False
            for key in email_aliases:
                if key in top_keys or key in required:
                    if empty(args.get(key)):
                        args[key] = user_email
                    matched = True
                    break
            if not matched and not top_keys and not required:
                args.setdefault("user_email", user_email)
            elif not matched and top_keys:
                for key in email_aliases:
                    if key in top_keys and empty(args.get(key)):
                        args[key] = user_email
                        matched = True
                        break
            if user_email and not any_email_set(args):
                merge_email_fallback(args, user_email, schema)

        out.append({"name": name, "arguments": args})
    return out
