from __future__ import annotations

import json
from typing import Any

_NON_JSON_SAMPLE_MAX = 3
_NON_JSON_LINE_MAX = 400


def _summarize_mcp_tool_item(item: dict[str, Any]) -> dict[str, Any]:
    """Extract a small, log-safe view of an MCP tool item (Codex JSONL shapes vary by version)."""
    out: dict[str, Any] = {}
    for key in ("name", "tool_name", "id", "status", "call_id"):
        v = item.get(key)
        if v is not None:
            out[key] = v
    err = item.get("error")
    if err is not None:
        if isinstance(err, dict):
            out["error"] = err.get("message") or err.get("code") or json.dumps(err)[:600]
        else:
            out["error"] = str(err)[:800]
    res = item.get("result")
    if res is not None:
        if isinstance(res, str):
            out["result_preview"] = res[:1200]
        else:
            try:
                out["result_preview"] = json.dumps(res)[:1200]
            except (TypeError, ValueError):
                out["result_preview"] = repr(res)[:400]
    return out


def parse_codex_exec_jsonl(stdout: str) -> dict[str, Any]:
    """
    Parse `codex exec --json` JSON Lines output.

    Codex emits newline-delimited JSON; outer `type` is often `item.completed` for finished items.
    """
    mcp_calls: list[dict[str, Any]] = []
    agent_messages: list[str] = []
    errors: list[dict[str, Any]] = []
    raw_types: dict[str, int] = {}
    item_type_counts: dict[str, int] = {}
    non_json_samples: list[str] = []
    non_json_line_count = 0
    lines_nonempty = 0

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        lines_nonempty += 1
        try:
            ev: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            non_json_line_count += 1
            if len(non_json_samples) < _NON_JSON_SAMPLE_MAX:
                non_json_samples.append(line[:_NON_JSON_LINE_MAX])
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
                errors.append({"phase": "turn.failed", "message": err.get("message"), "detail": err})
            elif isinstance(err, dict):
                errors.append({"phase": "turn.failed", "message": json.dumps(err)[:800]})
            else:
                errors.append({"phase": "turn.failed", "message": str(ev)[:1000]})
            continue

        if t != "item.completed":
            continue

        item = ev.get("item")
        if not isinstance(item, dict):
            continue

        itype = item.get("type")
        if isinstance(itype, str):
            item_type_counts[itype] = item_type_counts.get(itype, 0) + 1

        if itype == "mcp_tool_call":
            # Include success and failure (`item.status` completed | failed); see Codex JSONL cheatsheet.
            mcp_calls.append(item)
        elif isinstance(itype, str) and "tool" in itype.lower() and (
            "call" in itype.lower() or itype in ("tool_call", "mcp_call", "function_call")
        ):
            # Some Codex builds use alternate item.type labels for the same idea.
            mcp_calls.append(item)
        elif itype == "agent_message":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                agent_messages.append(text.strip())

    mcp_summaries = [_summarize_mcp_tool_item(x) for x in mcp_calls]

    hints: list[str] = []
    if not mcp_calls and not errors:
        hints.append(
            "No MCP tool calls were recorded in JSONL. Codex may have answered without calling tools "
            "(try a more explicit user task, CODEX_EXEC_EXTRA_ARGS, or a newer @openai/codex CLI)."
        )
    if non_json_line_count:
        hints.append(
            f"Codex stdout had {non_json_line_count} non-JSON line(s); output may be mixed text + JSONL "
            f"(see non_json_line_samples)."
        )
    if errors:
        hints.append(f"JSONL reported {len(errors)} error/turn.failed event(s); see errors[].")
    for s in mcp_summaries:
        st = s.get("status")
        if st and str(st).lower() in ("failed", "error"):
            hints.append(f"MCP tool item status={st!r}: {s.get('error', 'no error field')!r}")

    return {
        "mcp_tool_calls_completed": mcp_calls,
        "mcp_tool_summaries": mcp_summaries,
        "agent_messages": agent_messages,
        "final_agent_message": agent_messages[-1] if agent_messages else None,
        "errors": errors,
        "event_type_counts": raw_types,
        "item_type_counts": item_type_counts,
        "non_json_line_samples": non_json_samples,
        "non_json_line_count": non_json_line_count,
        "jsonl_nonempty_lines": lines_nonempty,
        "diagnostic_hints": hints,
    }
