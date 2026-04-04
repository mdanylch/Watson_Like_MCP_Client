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
        "Instructions:",
        "- Use MCP tools from that server when the user task requires data or actions only those tools provide.",
        "- Call a tool with valid JSON arguments when the tool schema requires fields (e.g. org_id).",
        "- Use only real tool results; do not invent tool output.",
        "- After tools return, give a short summary for the user.",
    ]
    ctx: list[str] = []
    if org_id:
        ctx.append(f"org_id: {org_id}")
    if user_email:
        ctx.append(f"user_email: {user_email}")
    if ctx:
        lines.extend(
            ["", "Request context — pass these in tool arguments when required:", *(f"- {c}" for c in ctx), ""]
        )

    lines.extend(["User task:", content.strip()])
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
        logger.info("Running Codex exec (jsonl), timeout=%ss", settings.codex_exec_timeout_sec)

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
            tail = (stderr + stdout)[-4000:]
            logger.warning("codex exec exited %s", proc.returncode)
            raise RuntimeError(f"codex exec failed (exit {proc.returncode}): {tail}")

        parsed = parse_codex_exec_jsonl(stdout)
        return {
            "mode": "codex_cli",
            "mcp_server_name": settings.codex_mcp_server_name,
            "parsed_jsonl": parsed,
            "jsonl_lines": len([ln for ln in stdout.splitlines() if ln.strip()]),
            "stderr_tail": stderr[-8000:] if stderr else "",
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
