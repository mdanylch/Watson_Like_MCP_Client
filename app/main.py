from __future__ import annotations

import logging
import traceback
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

app = FastAPI(title="BDB MCP Bridge", version="0.1.0")


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
        out["exception_type"] = type(exc).__name__
        out["exception_message"] = str(exc)
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
        logger.warning("MCP or router error: %s", e)
        # Always surface RuntimeError text (e.g. Codex missing); add traceback when EXPOSE_ERROR_DETAILS=1
        if settings.expose_error_details:
            detail: str | dict[str, Any] = _detail_payload(
                settings, status_code=502, public_message=str(e), exc=e
            )
        else:
            detail = str(e)
        raise HTTPException(status_code=502, detail=detail) from e
    except Exception as e:
        logger.exception("invoke failed")
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
