from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app.bdb_oauth import fetch_client_credentials_token
from app.codex_config import write_codex_mcp_config
from app.codex_jsonl import parse_codex_exec_jsonl
from app.config import Settings

logger = logging.getLogger(__name__)

# Cap how much Codex stdout we keep for API/diagnostics (bytes are UTF-8).
_STDOUT_DIAG_MAX = 48_000
_STDERR_DIAG_MAX = 32_000


def _format_exec_cmd_for_log(cmd: list[str]) -> str:
    """Log argv without dumping the full user prompt."""
    if not cmd:
        return ""
    if len(cmd) >= 1:
        head = cmd[:-1]
        tail = cmd[-1]
        quoted = " ".join(shlex.quote(x) for x in head)
        return f"{quoted} <prompt {len(tail)} chars>"
    return " ".join(shlex.quote(x) for x in cmd)


def _build_codex_prompt(
    server_name: str,
    content: str,
    org_id: str | None,
    user_email: str | None,
) -> str:
    """Prompt for `codex exec` — tool use depends on Codex + MCP session (see README troubleshooting)."""
    lines: list[str] = [
        f'You are using Cisco BDB via Model Context Protocol. The MCP server "{server_name}" is configured for this session.',
        "",
        "Hard rules (non-negotiable):",
        "- If the user asks for data, lists, lookups, or any action that requires BDB/MCP tools, you MUST call the "
        "appropriate tool in this same turn. Do not reply with only an acknowledgment, greeting, or promise to use the "
        "server later.",
        "- Prefer calling a tool over guessing. Use only real tool results; do not invent API or WXCC output.",
        "- Pass required tool arguments as JSON per each tool's schema (e.g. org_id as a string UUID when required).",
        "- After tools return, give a brief summary for the user.",
    ]
    ctx: list[str] = []
    if org_id:
        ctx.append(f"org_id: {org_id}")
    if user_email:
        ctx.append(f"user_email: {user_email}")
    if ctx:
        lines.extend(
            [
                "",
                "Context for tool arguments — include these in tools/call when the schema asks for them:",
                *(f"- {c}" for c in ctx),
                "",
            ]
        )

    lines.extend(
        [
            "User task (perform it now using MCP tools when applicable):",
            content.strip(),
        ]
    )
    return "\n".join(lines)


def _find_codex_binary(settings: Settings) -> str:
    exe = settings.codex_binary.strip() or "codex"
    if os.path.isabs(exe) and Path(exe).is_file():
        return exe
    found = shutil.which(exe)
    if not found:
        raise RuntimeError(
            "Codex CLI not found on PATH. Install with: npm install -g @openai/codex "
            "(see https://developers.openai.com/codex/cli/)"
        )
    return found


def _codex_env(
    settings: Settings,
    codex_home: Path,
    bearer: str,
    org_id: str | None,
    user_email: str | None,
) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(codex_home)
    key = settings.openai_api_key
    env["CODEX_API_KEY"] = key
    env["OPENAI_API_KEY"] = key

    env["BDB_MCP_BEARER_TOKEN"] = bearer
    oid = org_id if org_id is not None else settings.org_id
    em = user_email if user_email is not None else settings.user_email
    if oid:
        env["BDB_ORG_ID"] = oid
    if em:
        env["BDB_USER_EMAIL"] = em
    return env


async def invoke_codex_mcp_pipeline(
    settings: Settings,
    content: str,
    *,
    org_id: str | None = None,
    user_email: str | None = None,
) -> dict[str, Any]:
    """
    OAuth token → write Codex MCP config → `codex exec --json` with BDB MCP available.
    """
    token = await fetch_client_credentials_token(settings)
    codex_bin = _find_codex_binary(settings)

    tmp = Path(tempfile.mkdtemp(prefix="codex-mcp-bridge-"))
    try:
        write_codex_mcp_config(tmp, settings, org_id=org_id, user_email=user_email)
        prompt = _build_codex_prompt(
            settings.codex_mcp_server_name,
            content,
            org_id,
            user_email,
        )

        extra: list[str] = []
        raw = (settings.codex_exec_extra_args or "").strip()
        if raw:
            extra = shlex.split(raw, posix=os.name != "nt")
        cmd = [
            codex_bin,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--json",
            *extra,
            prompt,
        ]

        env = _codex_env(settings, tmp, token, org_id, user_email)
        logger.info(
            "Running Codex exec (jsonl): timeout=%ss mcp_url=%s mcp_server=%s org_id_set=%s user_email_set=%s cmd=%s",
            settings.codex_exec_timeout_sec,
            settings.mcp_base_url,
            settings.codex_mcp_server_name,
            bool(org_id or settings.org_id),
            bool(user_email or settings.user_email),
            _format_exec_cmd_for_log(cmd),
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(tmp),
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=settings.codex_exec_timeout_sec,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"codex exec exceeded timeout ({settings.codex_exec_timeout_sec}s)") from None

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            tail = (stderr + stdout)[-8000:]
            logger.warning(
                "codex exec failed: exit=%s stderr_bytes=%s stdout_bytes=%s tail=%s",
                proc.returncode,
                len(stderr_b),
                len(stdout_b),
                tail[:2000],
            )
            raise RuntimeError(f"codex exec failed (exit {proc.returncode}): {tail}")

        parsed = parse_codex_exec_jsonl(stdout)
        mcp_n = len(parsed.get("mcp_tool_calls_completed") or [])
        err_n = len(parsed.get("errors") or [])
        hints = parsed.get("diagnostic_hints") or []
        logger.info(
            "codex exec ok: jsonl_nonempty_lines=%s event_types=%s item_types=%s mcp_tool_calls=%s errors=%s",
            parsed.get("jsonl_nonempty_lines"),
            parsed.get("event_type_counts"),
            parsed.get("item_type_counts"),
            mcp_n,
            err_n,
        )
        if hints:
            for h in hints:
                logger.warning("codex diagnostic hint: %s", h)
        if mcp_n > 0:
            for i, s in enumerate(parsed.get("mcp_tool_summaries") or []):
                logger.info("mcp tool call [%s]: %s", i, s)
        else:
            logger.warning(
                "No MCP tool calls in JSONL — agent likely did not invoke tools. "
                "final_agent_message=%r",
                (parsed.get("final_agent_message") or "")[:500],
            )
        if err_n:
            logger.warning("codex JSONL errors: %s", parsed.get("errors"))

        out: dict[str, Any] = {
            "mode": "codex_cli",
            "mcp_server_name": settings.codex_mcp_server_name,
            "parsed_jsonl": parsed,
            "jsonl_lines": len([ln for ln in stdout.splitlines() if ln.strip()]),
            "stderr_tail": stderr[-8000:] if stderr else "",
        }
        if settings.invoke_verbose_diagnostics:
            out["diagnostics"] = {
                "codex_command": _format_exec_cmd_for_log(cmd),
                "mcp_base_url": settings.mcp_base_url,
                "stderr": stderr[-_STDERR_DIAG_MAX:] if stderr else "",
                "stdout_tail": stdout[-_STDOUT_DIAG_MAX:] if stdout else "",
                "hints": hints,
                "mcp_tool_summaries": parsed.get("mcp_tool_summaries"),
            }
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
