# BDB MCP bridge (Codex CLI + AWS App Runner)

## Default behavior: Python MCP + OpenAI (`ROUTER_MODE=openai_api`, default)

**AWS App Runner (managed Python)** has no **Codex CLI** (no Node/npm). The default **`openai_api`** mode uses the embedded MCP client + OpenAI tool routing.

## Optional: Codex CLI (`ROUTER_MODE=codex_cli`)

Use when the **`codex` binary is on `PATH`** (e.g. **Dockerfile** deployment with `npm install -g @openai/codex`). Set **`ROUTER_MODE=codex_cli`** in the environment.

1. Obtains a **Bearer token** from Cisco BDB Duo OAuth (`client_credentials`).
2. Writes a per-request **[Codex `config.toml`](https://developers.openai.com/codex/mcp)** that registers your BDB MCP endpoint as **streamable HTTP** with:
   - `bearer_token_env_var = "BDB_MCP_BEARER_TOKEN"` (runtime token)
   - optional `env_http_headers` for `X-Org-Id` / `X-User-Email` (from `ORG_ID` / `USER_EMAIL` env or request body)
3. Runs **`codex exec --json`** (non-interactive) so **Codex** plans work and invokes **MCP tools** on `scripts.cisco.com` through that configured server.
4. Parses the JSON Lines stream and returns completed **`mcp_tool_call`** items plus the last **`agent_message`** when present.

This matches OpenAI’s documented pattern: configure MCP in `config.toml`, then use `codex exec` in CI/automation with `CODEX_API_KEY`. See [Non-interactive mode](https://developers.openai.com/codex/noninteractive) and [Codex MCP](https://developers.openai.com/codex/mcp).

### Same stack without Codex

**`ROUTER_MODE=openai_api`** (default) — Python MCP SDK + OpenAI function calling; no `codex` binary required.

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
| `ROUTER_MODE` | No | `openai_api` (default, App Runner Python) or `codex_cli` (Docker / machine with Codex CLI). |
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
| `EXPOSE_ERROR_DETAILS` | No | Default `false`. Set **`true`** while debugging so `/invoke` errors include `exception_type`, `exception_message`, and `traceback` in the JSON `detail` object. **Turn off in production** (tracebacks can leak context). |
| `HTTP_SSL_VERIFY` | No | Default `true`. Set **`false`** only if you hit **`CERTIFICATE_VERIFY_FAILED`** behind corporate SSL inspection (local dev). **Avoid in production.** |
| `SSL_CA_BUNDLE` | No | Path to a **PEM** file with trusted CAs (e.g. corporate root + public roots). Prefer this over disabling verification when possible. |

Per-request overrides: `POST /invoke` JSON may include `org_id` and `user_email`.

## Run locally on Windows (PC)

Default mode **`ROUTER_MODE=openai_api`** does **not** require Node or Codex—only Python and your API keys.

**1. Python 3.11+** and a project folder (this repo).

**2. Virtualenv and dependencies**

```powershell
cd "C:\path\to\Watson_MCP_Client"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**3. Environment variables** (PowerShell session, or copy `env.example` to `.env` and fill values—`pydantic-settings` loads `.env` automatically):

```powershell
$env:CLIENT_ID_BDB = "your-client-id"
$env:CLIENT_SECRET_BDB = "your-secret"
$env:OPENAI_API_KEY = "sk-..."   # or CODEX_API_KEY / API_KEY_LLM
$env:ROUTER_MODE = "openai_api"
$env:EXPOSE_ERROR_DETAILS = "true"   # optional: full error JSON in responses while debugging
```

**Corporate network / SSL inspection:** If you see **`SSL: CERTIFICATE_VERIFY_FAILED`** or **`unable to get local issuer certificate`**, Python does not trust your intercept CA. Either:

- Point **`SSL_CA_BUNDLE`** at a PEM that includes your org’s root (and public CAs if needed), or  
- For quick local testing only: **`$env:HTTP_SSL_VERIFY = "false"`** (insecure; do not use in production).

**Important:** `HTTP_SSL_VERIFY` must be set in the **same environment as the uvicorn process**. Setting it only in the PowerShell window where you run **`Invoke-RestMethod`** does **nothing** for the server. Either: (1) stop uvicorn, run `$env:HTTP_SSL_VERIFY = "false"`, start uvicorn again in **that** window; or (2) put `HTTP_SSL_VERIFY=false` in a **`.env`** file in the project root (loaded when the app starts). On startup, logs show **`HTTP_SSL_VERIFY=...`** so you can confirm.

**4. Start the API** (from repo root, venv active):

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

**5. Test**

```powershell
curl.exe -s http://127.0.0.1:8080/health

curl.exe -s -X POST http://127.0.0.1:8080/invoke `
  -H "Content-Type: application/json" `
  -d "{\"content\": \"Your task\", \"org_id\": \"your-org\", \"user_email\": \"you@company.com\"}"
```

If `Invoke-WebRequest` is aliased as `curl`, use **`curl.exe`** so JSON is sent correctly.

To use **Codex CLI** locally instead, install Node, run `npm i -g @openai/codex`, set **`ROUTER_MODE=codex_cli`**, and ensure `codex` is on `PATH`.

## Docker

The `Dockerfile` installs **`@openai/codex`** globally so `codex` is on `PATH`.

```bash
docker build -t bdb-mcp-bridge .
docker run --rm -p 8080:8080 ^
  -e CLIENT_ID_BDB=... -e CLIENT_SECRET_BDB=... -e CODEX_API_KEY=... ^
  bdb-mcp-bridge
```

## AWS App Runner

### Option A — Container from `Dockerfile` (Codex CLI included)

1. Build and push the image to ECR, or connect App Runner to **source** with **Dockerfile** as the build type.
2. Set environment variables; use secrets for `CLIENT_SECRET_BDB` and `CODEX_API_KEY`.
3. Health check: **`GET /health`**.
4. Egress: Duo SSO, `scripts.cisco.com`, and OpenAI API endpoints used by Codex.

### Option B — Managed **Python 3.11** runtime (GitHub source, no Docker)

The App Runner Python **3.11** build image does **not** put `pip` on `PATH`. AWS documents using **`pip3`** and **`python3`** instead. See [Using the Python platform](https://docs.aws.amazon.com/apprunner/latest/dg/service-source-code-python.html).

**Build command (console)** — same as [webex-cc-mcp](https://github.com/mdanylch/webex-cc-mcp):

```text
pip3 install -r requirements.txt
```

**Start command (console)** — use the repo’s shell wrapper (installs deps again at runtime, which avoids common Python 3.11 “revised build” issues):

```text
sh start.sh
```

Or commit the repo’s **`apprunner.yaml`** and set **Configuration source** to **Configuration file**.

**If the build step still fails**, open the deployment **build log** in App Runner and find the **`pip`** error line (missing compiler, package build failure, etc.). This repo uses plain **`uvicorn`** (not `uvicorn[standard]`) to reduce native-extension failures on App Runner build hosts.

**Important:** The managed Python runtime **does not include Node.js or Codex CLI**. The app **defaults to `ROUTER_MODE=openai_api`**. To use **Codex CLI**, deploy the **`Dockerfile`** (Option A) and set **`ROUTER_MODE=codex_cli`**.

### Troubleshooting

| Symptom | Likely cause |
|--------|----------------|
| `pip: command not found` | Use **`pip3 install -r requirements.txt`**, not `pip`. |
| Codex / MCP failures on Python runtime | Set **`ROUTER_MODE=openai_api`** or switch to Dockerfile deployment. |
| **Web ACL** error in the console | Often an IAM/console issue loading AWS WAF association for the service, or no WAF attached. If you are not using WAF on App Runner, it is usually safe to ignore; otherwise ensure your user/role has `wafv2:GetWebACL` (and related) permissions. |
| **Application logs** empty / slow | Logs appear after a healthy instance is running. Failed builds or crashing tasks delay log groups; CloudWatch can lag by a minute or two. |
| **HTTP 429** / `insufficient_quota` / `RateLimitError` from OpenAI | Your **API key has no remaining quota** or billing is not enabled. Top up at [OpenAI billing](https://platform.openai.com/account/billing) or use another key / org project. |

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
