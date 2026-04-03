# BDB MCP bridge (Codex CLI + AWS App Runner)

## Primary behavior: Codex CLI (`ROUTER_MODE=codex_cli`, default)

1. Obtains a **Bearer token** from Cisco BDB Duo OAuth (`client_credentials`).
2. Writes a per-request **[Codex `config.toml`](https://developers.openai.com/codex/mcp)** that registers your BDB MCP endpoint as **streamable HTTP** with:
   - `bearer_token_env_var = "BDB_MCP_BEARER_TOKEN"` (runtime token)
   - optional `env_http_headers` for `X-Org-Id` / `X-User-Email` (from `ORG_ID` / `USER_EMAIL` env or request body)
3. Runs **`codex exec --json`** (non-interactive) so **Codex** plans work and invokes **MCP tools** on `scripts.cisco.com` through that configured server.
4. Parses the JSON Lines stream and returns completed **`mcp_tool_call`** items plus the last **`agent_message`** when present.

This matches OpenAI’s documented pattern: configure MCP in `config.toml`, then use `codex exec` in CI/automation with `CODEX_API_KEY`. See [Non-interactive mode](https://developers.openai.com/codex/noninteractive) and [Codex MCP](https://developers.openai.com/codex/mcp).

### Fallback: Python MCP + OpenAI function calling

Set **`ROUTER_MODE=openai_api`** to skip Codex CLI and use the embedded Python MCP client plus OpenAI tool routing (useful if `codex exec` cannot run in your environment).

## Install Codex CLI (local dev)

```bash
npm install -g @openai/codex
codex --version
```

Authentication for `codex exec` uses **`CODEX_API_KEY`** (or this app maps **`OPENAI_API_KEY` / `API_KEY_LLM`** to both `CODEX_API_KEY` and `OPENAI_API_KEY` inside the process). See [Authenticate in CI](https://developers.openai.com/codex/noninteractive).

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CLIENT_ID_BDB` | Yes | Duo OAuth client id. |
| `CLIENT_SECRET_BDB` | Yes | Duo OAuth client secret (secret in App Runner). |
| `CODEX_API_KEY` or `OPENAI_API_KEY` or `API_KEY_LLM` | Yes | API key for **`codex exec`** (same as OpenAI API key for default provider). |
| `ROUTER_MODE` | No | `codex_cli` (default) or `openai_api`. |
| `MCP_BASE_URL` | No | Default: `https://scripts.cisco.com/api/v2/mcp/namespace/wxcc_mcp_2` |
| `BDB_TOKEN_URL` | No | Default Duo token URL from your integration. |
| `ORG_ID` | No | Passed via `env_http_headers` → `X-Org-Id` when set. |
| `USER_EMAIL` | No | Passed via `env_http_headers` → `X-User-Email` when set. |
| `CODEX_MCP_SERVER_NAME` | No | Config key / prompt name (default `bdb_wxcc`). Must match the name Codex sees in `config.toml`. |
| `CODEX_EXEC_TIMEOUT_SEC` | No | Default `600`. |
| `CODEX_SANDBOX` | No | `read-only` (default), `workspace-write`, or `danger-full-access`. |
| `CODEX_BINARY` | No | Default `codex` (must be on `PATH`; Docker image installs via npm). |
| `ROUTER_MODEL` | No | Only used when `ROUTER_MODE=openai_api`. |
| `ASSISTANT_FOLLOWUP` | No | Only used when `ROUTER_MODE=openai_api`. |
| `PORT` | No | App Runner sets this; default `8080`. |

Per-request overrides: `POST /invoke` JSON may include `org_id` and `user_email`.

## Local run

Install **Node.js** and **Codex CLI** (`npm i -g @openai/codex`), then:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

set CLIENT_ID_BDB=...
set CLIENT_SECRET_BDB=...
set CODEX_API_KEY=...

uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Invoke:

```bash
curl -s -X POST http://127.0.0.1:8080/invoke ^
  -H "Content-Type: application/json" ^
  -d "{\"content\": \"Your task in natural language\"}"
```

## Docker

The `Dockerfile` installs **`@openai/codex`** globally so `codex` is on `PATH`.

```bash
docker build -t bdb-mcp-bridge .
docker run --rm -p 8080:8080 ^
  -e CLIENT_ID_BDB=... -e CLIENT_SECRET_BDB=... -e CODEX_API_KEY=... ^
  bdb-mcp-bridge
```

## AWS App Runner

1. Build and push the image (includes Codex CLI).
2. Configure the same environment variables; prefer secrets for `CLIENT_SECRET_BDB` and `CODEX_API_KEY`.
3. Health check: **`GET /health`**.
4. Egress: Duo SSO, `scripts.cisco.com`, and OpenAI API endpoints used by Codex.

### Testing on App Runner

```bash
curl -s https://YOUR-SERVICE.awsapprunner.com/health

curl -s -X POST https://YOUR-SERVICE.awsapprunner.com/invoke ^
  -H "Content-Type: application/json" ^
  -d "{\"content\": \"Describe what you want the MCP tool to do\"}"
```

If **`parsed_jsonl`** is empty but Codex ran, you may be on a Codex build where JSONL and MCP interact oddly; track OpenAI Codex releases or temporarily set **`ROUTER_MODE=openai_api`**.

## Access prerequisites

1. Duo / BDB OAuth client credentials for the token URL.
2. Correct **MCP URL** / namespace from BDB.
3. **OpenAI API key** (or org-approved key) for **`codex exec`**.
4. Confirm **header** names with BDB; adjust `app/codex_config.py` if they differ from `X-Org-Id` / `X-User-Email`.

## Security

- Do not log tokens or secrets; errors truncate stderr.
- Treat `CLIENT_SECRET_BDB` and API keys as managed secrets.
