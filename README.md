# BDB MCP bridge (Codex CLI only)

FastAPI service: **Duo OAuth** (client credentials) → writes **`~/.codex/config.toml`** in a temp home → runs **`codex exec --json`** so the [Codex CLI](https://developers.openai.com/codex/cli/) uses your BDB MCP server (streamable HTTP).

**There are no separate REST routes for `tools/list` or `tools/call`.** Only **`POST /invoke`** runs Codex.

## Requirements

- Python 3.11+
- **`codex` on PATH** — `npm install -g @openai/codex`
- Env: `CLIENT_ID_BDB`, `CLIENT_SECRET_BDB`, `CODEX_API_KEY` (see `env.example`)

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8080/invoke" -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body (@{ content = "List WXCC address books for this org."; org_id = "YOUR-ORG-UUID" } | ConvertTo-Json -Depth 5 -Compress)
```

Response includes **`parsed_jsonl`** from **`codex exec --json`**. Tool activity appears under **`mcp_tool_calls_completed`** when Codex actually emits MCP tool events.

## Endpoints

| Method | Path      | Description |
|--------|-----------|-------------|
| GET    | `/health` | Liveness |
| POST   | `/invoke` | Body: `content`, optional `org_id`, `user_email` |

## Troubleshooting: MCP + `codex exec` (production Codex client)

This app **does not** implement MCP inside Python. It only:

1. Fetches an OAuth token and sets **`BDB_MCP_BEARER_TOKEN`** (and optional **`BDB_ORG_ID`** / **`BDB_USER_EMAIL`**).
2. Writes **`[mcp_servers.<name>]`** in a temporary **`HOME`** with **`url`**, **`bearer_token_env_var`**, and optional **`env_http_headers`** (see [Codex MCP](https://developers.openai.com/codex/mcp)).
3. Runs **`codex exec`** with that **`HOME`**.

If **`parsed_jsonl.mcp_tool_calls_completed`** is empty but you get short “Understood…” text, **Codex chose not to call tools** in that run. That is controlled by **Codex + your CLI version**, not by this bridge alone.

**Checklist (Codex-side):**

1. **Upgrade Codex** — `npm update -g @openai/codex`; confirm **`codex exec --help`** matches the flags you set in **`CODEX_EXEC_EXTRA_ARGS`** (e.g. `--full-auto` only if supported).
2. **Timeouts** — BDB may be slow. Tune **`MCP_STARTUP_TIMEOUT_SEC`** and **`MCP_TOOL_TIMEOUT_SEC`** in `.env` (written into `config.toml` as `startup_timeout_sec` / `tool_timeout_sec`).
3. **TLS** — If token fetch works but MCP fails, set **`HTTP_SSL_VERIFY`** / **`SSL_CA_BUNDLE`** for the **server** process.
4. **Same config manually** — Copy the generated pattern: run **`codex`** with **`HOME`** pointing at a dir that contains **`.codex/config.toml`** with your **`MCP_BASE_URL`**, **`BDB_MCP_BEARER_TOKEN`**, and headers — then run **`codex exec --json "…"`** in a shell. If tools still never run, the issue is **Codex ↔ MCP**, not FastAPI.
5. **Upstream behavior** — Track **`@openai/codex`** releases and issues (e.g. `codex exec` vs interactive TUI differing on MCP tool dispatch).

Optional: **`CODEX_EXEC_EXTRA_ARGS=--full-auto`** if your **`codex exec --help`** lists it (do not add flags your CLI rejects).

TLS for Duo: **`HTTP_SSL_VERIFY`**, **`SSL_CA_BUNDLE`** (`env.example`).

## BDB MCP server / namespace — what you can adjust (server side)

Codex uses the same **streamable HTTP** MCP transport as the official Python sample (`streamablehttp_client` + session `initialize` → `list_tools` → `call_tool`). Your bridge already passes a **Bearer token** from **client ID + secret** (Duo OAuth) and optional **`X-Org-Id`** / **`X-User-Email`** via **`env_http_headers`**, matching typical BDB tenancy.

On the **BDB / tool definition** side, things that help **every** client (including Codex) are:

1. **Tool `inputSchema`** — Clear **`properties`**, a correct **`required`** array (e.g. `org_id`), and **`additionalProperties: false`** where appropriate so models know exactly what to send.
2. **Descriptions** — Short, action-oriented **`description`** text on each tool so routing models (including Codex) know *when* to call which tool.
3. **OAuth / entitlements** — Confirm the **client-credentials** app used for BDB is allowed to call **this** MCP namespace and tools (scopes / allowlists if your platform has them).
4. **Headers** — If the server requires tenancy, document which headers must be set (**`X-Org-Id`**, **`X-User-Email`**, etc.). This app maps request/env values into those headers for Codex.
5. **Performance** — Keep **`initialize`** and **`tools/list`** fast enough for Codex defaults; tune **`MCP_STARTUP_TIMEOUT_SEC`** / **`MCP_TOOL_TIMEOUT_SEC`** here if BDB is slow.
6. **URL** — No trailing spaces in the MCP base URL (easy mistake in samples).
7. **Protocol** — Stay aligned with the **MCP streamable HTTP** spec your `mcp` Python package expects; Codex’s client must be able to complete **`initialize`** and list tools the same way your sample does.

**Reality check:** If your **Python sample** (same token, same URL, same headers) successfully runs **`call_tool`**, the BDB endpoint is largely doing its job; **Codex `exec`** not calling tools is then mostly **Codex agent behavior / CLI version**, not something you fix only by changing BDB JSON. Improving **schemas and descriptions** still helps Codex choose tools when it *does* attempt tool use.
