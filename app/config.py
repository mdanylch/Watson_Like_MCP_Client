from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
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

    # MCP server (streamable HTTP) — used in Codex ~/.codex/config.toml
    mcp_base_url: str = Field(
        default="https://scripts.cisco.com/api/v2/mcp/namespace/wxcc_mcp_2",
        validation_alias="MCP_BASE_URL",
    )
    mcp_startup_timeout_sec: int = Field(
        default=45,
        ge=5,
        le=300,
        validation_alias="MCP_STARTUP_TIMEOUT_SEC",
        description="Seconds for Codex to connect to streamable HTTP MCP (config.toml startup_timeout_sec).",
    )
    mcp_tool_timeout_sec: int = Field(
        default=120,
        ge=10,
        le=600,
        validation_alias="MCP_TOOL_TIMEOUT_SEC",
        description="Seconds per MCP tool call (config.toml tool_timeout_sec).",
    )

    # Optional org / user context for upstream headers (if your BDB contract requires them)
    org_id: str | None = Field(default=None, validation_alias="ORG_ID")
    user_email: str | None = Field(default=None, validation_alias="USER_EMAIL")

    # Passed to ``codex exec`` as CODEX_API_KEY / OPENAI_API_KEY (see OpenAI Codex docs)
    openai_api_key: str = Field(
        validation_alias=AliasChoices("CODEX_API_KEY", "OPENAI_API_KEY", "API_KEY_LLM"),
    )

    codex_binary: str = Field(default="codex", validation_alias="CODEX_BINARY")
    codex_mcp_server_name: str = Field(default="bdb_wxcc", validation_alias="CODEX_MCP_SERVER_NAME")
    codex_exec_timeout_sec: int = Field(default=600, validation_alias="CODEX_EXEC_TIMEOUT_SEC")
    # Extra flags for `codex exec` (space-separated). See `codex exec --help` on your machine.
    # Example (newer CLIs): --full-auto   or   --ask-for-approval never
    codex_exec_extra_args: str = Field(default="", validation_alias="CODEX_EXEC_EXTRA_ARGS")

    # HTTP server
    host: str = Field(default="0.0.0.0", validation_alias="HOST")
    port: int = Field(default=8080, validation_alias="PORT")

    # When true, /invoke returns exception type + message in JSON (for local/debug)
    expose_error_details: bool = Field(default=False, validation_alias="EXPOSE_ERROR_DETAILS")

    # When true, /invoke includes a ``diagnostics`` object (stderr, stdout sample, MCP hints) and logs detail
    invoke_verbose_diagnostics: bool = Field(default=False, validation_alias="INVOKE_VERBOSE_DIAGNOSTICS")

    # TLS for httpx (Duo token fetch). Corporate SSL inspection often needs a PEM bundle.
    http_ssl_verify: bool = Field(default=True, validation_alias="HTTP_SSL_VERIFY")
    ssl_ca_bundle: str | None = Field(
        default=None,
        validation_alias="SSL_CA_BUNDLE",
        description="Path to a PEM file with extra CA certs (e.g. corporate root). Used when HTTP_SSL_VERIFY is true.",
    )

    @field_validator("http_ssl_verify", mode="before")
    @classmethod
    def _coerce_http_ssl_verify(cls, v: object) -> bool:
        if v is None or v == "":
            return True
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
