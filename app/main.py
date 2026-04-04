from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.mcp_runner import invoke_mcp_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _deepest_cause(exc: BaseException) -> BaseException:
    """Unwrap ExceptionGroup (e.g. MCP TaskGroup) to a leaf exception for clearer messages."""
    if isinstance(exc, BaseExceptionGroup):
        if not exc.exceptions:
            return exc
        return _deepest_cause(exc.exceptions[0])
    return exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    logger.info(
        "Startup: Codex CLI bridge HTTP_SSL_VERIFY=%s SSL_CA_BUNDLE=%s",
        s.http_ssl_verify,
        "(path set)" if s.ssl_ca_bundle else "(none)",
    )
    if s.http_ssl_verify:
        logger.info(
            "TLS: verification ON. If CERTIFICATE_VERIFY_FAILED appears, set HTTP_SSL_VERIFY=false "
            "or SSL_CA_BUNDLE in the **server** environment, then restart uvicorn — not only in the client shell."
        )
    yield


app = FastAPI(title="BDB MCP Bridge", version="0.1.0", lifespan=lifespan)


class InvokeRequest(BaseModel):
    content: str = Field(..., min_length=1, description="User task / question for the MCP tools")
    org_id: str | None = Field(default=None, description="Overrides ORG_ID for this request")
    user_email: str | None = Field(default=None, description="Overrides USER_EMAIL for this request")


def _detail_payload(
    settings: Settings,
    *,
    status_code: int,
    public_message: str,
    exc: BaseException | None = None,
    extra: dict[str, Any] | None = None,
) -> str | dict[str, Any]:
    """Return a string for simple errors, or a dict when EXPOSE_ERROR_DETAILS is on."""
    if not settings.expose_error_details:
        return public_message
    out: dict[str, Any] = {
        "message": public_message,
        "status_code": status_code,
    }
    if extra:
        out.update(extra)
    if exc is not None:
        root = _deepest_cause(exc)
        out["exception_type"] = type(exc).__name__
        out["exception_message"] = str(exc)
        if root is not exc:
            out["root_cause_type"] = type(root).__name__
            out["root_cause_message"] = str(root)
        out["traceback"] = traceback.format_exc()
    return out


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/invoke")
async def invoke(body: InvokeRequest, settings: Settings = Depends(get_settings)) -> JSONResponse:
    try:
        result = await invoke_mcp_pipeline(
            settings,
            body.content,
            org_id=body.org_id,
            user_email=body.user_email,
        )
    except httpx.HTTPStatusError as e:
        body_preview = (e.response.text or "")[:2000]
        logger.warning(
            "Upstream HTTP %s %s: %s",
            e.response.status_code,
            e.request.url,
            body_preview,
        )
        detail = _detail_payload(
            settings,
            status_code=502,
            public_message="Upstream HTTP error (token or MCP)",
            exc=e,
            extra={
                "upstream_status": e.response.status_code,
                "upstream_url": str(e.request.url),
                "upstream_body_preview": body_preview,
            },
        )
        raise HTTPException(status_code=502, detail=detail) from e
    except RuntimeError as e:
        logger.warning("Codex or upstream error: %s", e)
        if settings.expose_error_details:
            detail: str | dict[str, Any] = _detail_payload(
                settings, status_code=502, public_message=str(e), exc=e
            )
        else:
            detail = str(e)
        raise HTTPException(status_code=502, detail=detail) from e
    except Exception as e:
        root = _deepest_cause(e)
        logger.exception("invoke failed (root cause: %s: %s)", type(root).__name__, root)
        detail = _detail_payload(
            settings,
            status_code=500,
            public_message="Internal error",
            exc=e,
        )
        raise HTTPException(status_code=500, detail=detail) from e
    return JSONResponse(content=result)


def main() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port)


if __name__ == "__main__":
    main()
