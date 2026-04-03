from __future__ import annotations

import json
from typing import Any


def parse_codex_exec_jsonl(stdout: str) -> dict[str, Any]:
    """
    Parse `codex exec --json` JSON Lines output.

    Codex emits newline-delimited JSON; outer `type` is often `item.completed` for finished items.
    """
    mcp_calls: list[dict[str, Any]] = []
    agent_messages: list[str] = []
    errors: list[dict[str, Any]] = []
    raw_types: dict[str, int] = {}

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue

        t = ev.get("type")
        if isinstance(t, str):
            raw_types[t] = raw_types.get(t, 0) + 1

        if t == "error":
            errors.append(ev)
            continue

        if t == "turn.failed":
            err = ev.get("error")
            if isinstance(err, dict) and err.get("message"):
                errors.append({"phase": "turn.failed", "message": err.get("message")})
            continue

        if t != "item.completed":
            continue

        item = ev.get("item")
        if not isinstance(item, dict):
            continue

        itype = item.get("type")
        if itype == "mcp_tool_call":
            # Include success and failure (`item.status` completed | failed); see Codex JSONL cheatsheet.
            mcp_calls.append(item)
        elif itype == "agent_message":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                agent_messages.append(text.strip())

    return {
        "mcp_tool_calls_completed": mcp_calls,
        "agent_messages": agent_messages,
        "final_agent_message": agent_messages[-1] if agent_messages else None,
        "errors": errors,
        "event_type_counts": raw_types,
    }
