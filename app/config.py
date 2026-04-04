from __future__ import annotations

from functools import lru_cache

from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # BDB / Duo OAuth (client credentials)
    bdb_token_url: str = Field(
        default="https://sso-dbbfec7f.sso.duosecurity.com/oauth/DID1LHEMWQZDEGZ7FAXX/token",
        validation_alias="BDB_TOKEN_URL",
    )
    client_id_bdb: str = Field(validation_alias="CLIENT_ID_BDB")
    client_secret_bdb: str = Field(validation_alias="CLIENT_SECRET_BDB")

    # MCP server (streamable HTTP)
    mcp_base_url: str = Field(
        default="https://scripts.cisco.com/api/v2/mcp/namespace/wxcc_mcp_2",
        validation_alias="MCP_BASE_URL",
    )

    # Optional org / user context for upstream headers (if your BDB contract requires them)
    org_id: str | None = Field(default=None, validation_alias="ORG_ID")
    user_email: str | None = Field(default=None, validation_alias="USER_EMAIL")

    # API key: used by Codex CLI (`codex exec` / `CODEX_API_KEY`) and by optional OpenAI-router mode
    openai_api_key: str = Field(
        validation_alias=AliasChoices("CODEX_API_KEY", "OPENAI_API_KEY", "API_KEY_LLM"),
        description="Set in App Runner secrets; Codex exec uses CODEX_API_KEY per OpenAI docs.",
    )
    openai_base_url: str | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    router_model: str = Field(default="gpt-4o-mini", validation_alias="ROUTER_MODEL")

    # codex_cli needs the Codex binary (e.g. Dockerfile). App Runner managed Python has no Node/npm — use openai_api there.
    router_mode: Literal["codex_cli", "openai_api"] = Field(
        default="openai_api",
        validation_alias="ROUTER_MODE",
    )
    codex_binary: str = Field(default="codex", validation_alias="CODEX_BINARY")
    codex_mcp_server_name: str = Field(default="bdb_wxcc", validation_alias="CODEX_MCP_SERVER_NAME")
    codex_exec_timeout_sec: int = Field(default=600, validation_alias="CODEX_EXEC_TIMEOUT_SEC")
    codex_sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = Field(
        default="read-only",
        validation_alias="CODEX_SANDBOX",
    )

    # HTTP server
    host: str = Field(default="0.0.0.0", validation_alias="HOST")
    port: int = Field(default=8080, validation_alias="PORT")

    # Behavior
    assistant_followup: bool = Field(
        default=True,
        validation_alias="ASSISTANT_FOLLOWUP",
        description="If true, run a second LLM call to summarize tool results in natural language.",
    )

    # When true, /invoke returns exception type + message in JSON (for local/debug). Turn off in untrusted production.
    expose_error_details: bool = Field(default=False, validation_alias="EXPOSE_ERROR_DETAILS")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
