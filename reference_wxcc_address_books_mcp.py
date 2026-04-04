"""
BDB task: fetch WXCC address book via proxy (no bearer token).

BDB entrypoint: ``task(env, org_id, ...)`` — JSON string result.

MCP integration (for MCP servers / clients):
  - ``get_mcp_tools()`` — return value for ``tools/list`` (name + inputSchema per MCP).
  - ``invoke_mcp_tool(env, name, arguments)`` — return value for ``tools/call`` (JSON string).

**Tenant org (Codex / MCP):** ``org_id`` is a **tool argument** in ``inputSchema`` and ``tools/call``.
Clients should pass it explicitly (e.g. your bridge puts org in the user prompt so the model can
fill ``tools/call`` — that is your “chat” until a UI exists). You do **not** need ``CONTACT_CENTER_ORG_ID``
in ``.env`` if every call includes ``org_id`` or BDB injects it into ``env.session_info``.

Session-based fallbacks (``ORG_ID_SESSION_KEYS``) remain for BDB deployments that inject context when
the tool call omits ``org_id``.
"""
__copyright__ = "Copyright (c) 2018-2025 Cisco Systems. All rights reserved."

import json
import logging
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _fmt = logging.Formatter(
        "%(asctime)s %(funcName)s -> [%(levelname)s]  %(message)s"
    )
    _h = logging.StreamHandler()
    _h.setFormatter(_fmt)
    logger.addHandler(_h)

ALLOWED_WXCC_HOSTS = frozenset({
    "api.wxcc-us1.cisco.com",
    "api.wxcc-eu1.cisco.com",
    "api.wxcc-us2.cisco.com",
})
UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
PROXY_BASE = "https://scripts.cisco.com/api/v2/jobs"

# Canonical MCP / BDB tool name (``tools/list`` ``name`` and primary ``tools/call`` ``name``).
TOOL_GET_ADDRESS_BOOKS = "get_address_books"

# Friendly or legacy names from namespace UI / old jobs → canonical tool name.
MCP_TOOL_ALIASES: dict[str, str] = {
    "Mykola_Test": TOOL_GET_ADDRESS_BOOKS,
}

TOOL_DESCRIPTION_ADDRESS_BOOKS = (
    "Retrieve Webex Contact Center (WXCC) v3 address books for a tenant. "
    "Requires org_id (UUID) in tool arguments for Codex-style clients. "
    "Uses Cisco scripts proxy; auth from env.session_info (bdb_jwt or access_token)."
)

DEFAULT_BASE_URL = "api.wxcc-us1.cisco.com"
DEFAULT_PROXY_JOB = "WxCC_CMS_Proxy"

ORG_ID_SESSION_KEYS: tuple[str, ...] = (
    "org_id",
    "organization_id",
    "wxcc_org_id",
    "tenant_org_id",
    "CONTACT_CENTER_ORG_ID",
)


def _canonical_tool_name(name: str) -> str:
    n = name.strip()
    return MCP_TOOL_ALIASES.get(n, n)


def _org_id_from_session(session_info: dict[str, Any]) -> str | None:
    for key in ORG_ID_SESSION_KEYS:
        val = session_info.get(key)
        if isinstance(val, str):
            s = val.strip()
            if s:
                return s
    return None


def resolve_org_id(env: Any, explicit: str | None) -> str | None:
    """Explicit tools/call org_id wins; else first match in env.session_info."""
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    session_info = getattr(env, "session_info", None) or {}
    if not isinstance(session_info, dict):
        return None
    return _org_id_from_session(session_info)


# MCP ``tools/list`` — org_id required for Codex discovery/validation; optional base_url/proxy_job for task parity.
MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": TOOL_GET_ADDRESS_BOOKS,
        "description": TOOL_DESCRIPTION_ADDRESS_BOOKS,
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {
                    "type": "string",
                    "description": (
                        "WXCC tenant organization ID (UUID v4). Pass in tools/call (Codex). "
                        "If omitted at runtime, server may use session_info keys: "
                        f"{', '.join(ORG_ID_SESSION_KEYS)}."
                    ),
                    "pattern": (
                        "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
                        "[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
                    ),
                },
                "base_url": {
                    "type": "string",
                    "description": "WXCC API hostname (allowed region).",
                    "enum": sorted(ALLOWED_WXCC_HOSTS),
                    "default": DEFAULT_BASE_URL,
                },
                "proxy_job": {
                    "type": "string",
                    "description": "Cisco scripts API v2 job name for the WXCC proxy.",
                    "default": DEFAULT_PROXY_JOB,
                },
            },
            "required": ["org_id"],
            "additionalProperties": False,
        },
    },
]


def get_mcp_tools() -> list[dict[str, Any]]:
    """Return tool definitions for MCP ``tools/list`` (copy to avoid accidental mutation)."""
    return json.loads(json.dumps(MCP_TOOLS))


def invoke_mcp_tool(
    env: Any,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> str:
    """
    MCP ``tools/call``: resolve aliases (e.g. Mykola_Test → get_address_books), then dispatch.

    Response shape matches BDB ``task()``: ``{"success", "message", "tool_response"}``.
    """
    if not isinstance(name, str):
        return json.dumps({
            "success": False,
            "message": "tool name must be a string",
            "tool_response": None,
        })

    name = _canonical_tool_name(name)
    args = dict(arguments) if arguments else {}

    if name == TOOL_GET_ADDRESS_BOOKS:
        raw_org = args.get("org_id")
        base_url = args.get("base_url", DEFAULT_BASE_URL)
        proxy_job = args.get("proxy_job", DEFAULT_PROXY_JOB)

        if raw_org is not None and not isinstance(raw_org, str):
            return json.dumps({
                "success": False,
                "message": "org_id must be a string when provided",
                "tool_response": None,
            })
        org_id = resolve_org_id(env, raw_org)
        if org_id is None:
            return json.dumps({
                "success": False,
                "message": (
                    "Missing org_id: pass org_id in tools/call arguments, or set it in env.session_info "
                    f"({', '.join(ORG_ID_SESSION_KEYS)})."
                ),
                "tool_response": None,
            })
        if not isinstance(base_url, str):
            return json.dumps({
                "success": False,
                "message": "base_url must be a string",
                "tool_response": None,
            })
        if not isinstance(proxy_job, str):
            return json.dumps({
                "success": False,
                "message": "proxy_job must be a string",
                "tool_response": None,
            })
        return json.dumps(get_address_books(env, org_id, base_url, proxy_job))

    return json.dumps({
        "success": False,
        "message": (
            f"Unknown tool: {name!r}. Supported names: {TOOL_GET_ADDRESS_BOOKS!r} "
            f"or aliases {sorted(MCP_TOOL_ALIASES)!r}."
        ),
        "tool_response": None,
    })


def _validate_org_id(org_id: str) -> bool:
    return bool(org_id and isinstance(org_id, str) and UUID4_RE.match(org_id.strip()))


def _validate_base_url(host: str) -> bool:
    return bool(host and isinstance(host, str) and host.strip().lower() in ALLOWED_WXCC_HOSTS)


def _normalize_wxcc_host(host: str) -> str:
    return host.strip().lower()


def api_call(env: Any, method: str, url: str, payload: Any = None, proxy_job: str = "WxCC_CMS_Proxy") -> dict[str, Any]:
    session_info = getattr(env, "session_info", None) or {}
    if not isinstance(session_info, dict):
        session_info = {}
    token = session_info.get("bdb_jwt") or session_info.get("access_token")
    if not token:
        return {"error": "Missing BDB session token (bdb_jwt or access_token in session_info)"}

    body = {
        "printLogs": False,
        "input": {
            "env": vars(env),
            "I_httpmethod": method,
            "I_url": url,
            "I_payload": payload if payload is not None else {},
        },
        "output": "json",
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}

    try:
        response = requests.post(f"{PROXY_BASE}/{proxy_job}", json=body, headers=headers, timeout=60)
        if response.ok:
            return response.json()
        try:
            err_body = response.json()
        except Exception:
            err_body = response.text[:2000] if response.text else None
        return {
            "error": f"{response.status_code} {response.reason} for url: {response.url}",
            "status_code": response.status_code,
            "body": err_body,
        }
    except requests.RequestException as e:
        return {"error": str(e)}


def _get_address_book(env: Any, org_id: str, base_url: str, proxy_job: str) -> dict[str, Any]:
    if not _validate_org_id(org_id):
        raise ValueError("Invalid org_id format")
    if not _validate_base_url(base_url):
        raise ValueError("Invalid or disallowed base_url")

    host = _normalize_wxcc_host(base_url)
    path = f"/organization/{org_id.strip()}/v3/address-book"
    full_url = f"https://{host}{path}"
    response = api_call(env, "GET", full_url, proxy_job=proxy_job)

    if "error" in response:
        detail = response["error"]
        if response.get("body") is not None:
            b = response["body"]
            detail = f"{detail} | proxy response: {b}" if isinstance(b, str) else f"{detail} | proxy response: {b!r}"
        return {"err": "proxy_error", "detail": detail}

    data = response.get("data", {})
    variables = data.get("variables", {})
    result_descriptor = data.get("result")

    result = None
    if isinstance(result_descriptor, dict) and "key" in result_descriptor:
        result = variables.get(result_descriptor["key"])
    if result is None or (isinstance(result, str) and not result.strip()):
        result = variables.get("result") or variables.get("O_response")

    if result is None or (isinstance(result, str) and not result.strip()):
        return {"err": "proxy_empty_result", "detail": "Proxy returned no data."}
    if isinstance(result, dict) and result.get("err"):
        return result

    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            pass

    return result


def get_address_books(
    env: Any,
    org_id: str,
    base_url: str,
    proxy_job: str,
) -> dict[str, Any]:
    """Fetch WXCC address book list for the given organization via proxy."""
    logger.info("Address books task invoked for org %s (base_url=%s)", org_id, base_url)
    try:
        data = _get_address_book(env, org_id, base_url, proxy_job)
    except ValueError as e:
        logger.warning("Validation failed: %s", e)
        return {
            "success": False,
            "message": str(e),
            "tool_response": None,
        }
    except requests.RequestException as e:
        logger.error("Request failed: %s", e)
        return {
            "success": False,
            "message": f"Request failed: {e}",
            "tool_response": None,
        }
    except Exception as e:
        logger.exception("Unexpected error")
        return {
            "success": False,
            "message": f"An unexpected error occurred: {e}",
            "tool_response": None,
        }

    if isinstance(data, dict) and data.get("err"):
        return {
            "success": False,
            "message": data.get("detail", data.get("err", "Unknown error")),
            "tool_response": None,
        }
    logger.info("Successfully retrieved address book data for org %s", org_id)
    return {
        "success": True,
        "message": "Successfully retrieved address books from WXCC via proxy",
        "tool_response": data,
    }


def task(
    env: "bdblib.Env",
    org_id: str,
    base_url: str = DEFAULT_BASE_URL,
    proxy_job: str = DEFAULT_PROXY_JOB,
    action: str = TOOL_GET_ADDRESS_BOOKS,
) -> str:
    """
    BDB entrypoint. Same JSON result shape as :func:`invoke_mcp_tool`.

    ``action`` may be the canonical tool name or a key from :data:`MCP_TOOL_ALIASES` (e.g. ``Mykola_Test``).
    """
    act = _canonical_tool_name((action or TOOL_GET_ADDRESS_BOOKS).strip() or TOOL_GET_ADDRESS_BOOKS)
    if act != TOOL_GET_ADDRESS_BOOKS:
        return json.dumps({
            "success": False,
            "message": f"Invalid action: {action!r}. Supported: {TOOL_GET_ADDRESS_BOOKS!r} or aliases {sorted(MCP_TOOL_ALIASES)!r}.",
            "tool_response": None,
        })
    return invoke_mcp_tool(
        env,
        TOOL_GET_ADDRESS_BOOKS,
        {"org_id": org_id, "base_url": base_url, "proxy_job": proxy_job},
    )


__all__ = [
    "ALLOWED_WXCC_HOSTS",
    "DEFAULT_BASE_URL",
    "DEFAULT_PROXY_JOB",
    "MCP_TOOL_ALIASES",
    "MCP_TOOLS",
    "ORG_ID_SESSION_KEYS",
    "TOOL_DESCRIPTION_ADDRESS_BOOKS",
    "TOOL_GET_ADDRESS_BOOKS",
    "api_call",
    "get_address_books",
    "get_mcp_tools",
    "invoke_mcp_tool",
    "resolve_org_id",
    "task",
]
