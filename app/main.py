from __future__ import annotations

import logging

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.mcp_runner import invoke_mcp_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="BDB MCP Bridge", version="0.1.0")


class InvokeRequest(BaseModel):
    content: str = Field(..., min_length=1, description="User task / question for the MCP tools")
    org_id: str | None = Field(default=None, description="Overrides ORG_ID for this request")
    user_email: str | None = Field(default=None, description="Overrides USER_EMAIL for this request")


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
        logger.warning("HTTP error from token or MCP upstream: %s", e.response.status_code)
        raise HTTPException(status_code=502, detail="Upstream HTTP error (token or MCP)") from e
    except RuntimeError as e:
        logger.warning("MCP or router error: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        logger.exception("Unexpected failure")
        raise HTTPException(status_code=500, detail="Internal error") from e
    return JSONResponse(content=result)


def main() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port)


if __name__ == "__main__":
    main()
