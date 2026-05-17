"""Central application settings.

Single source of truth for every environment variable the agent reads.
Modules should import `settings` from here rather than calling
`os.getenv` directly — this keeps env-var spellings consistent, makes
defaults visible in one place, and gives us typed validation for free.

Most fields are Optional with sensible defaults. The Pydantic Settings
loader resolves them in this order:

  1. Real env vars (incl. anything `dotenv` already loaded into the process)
  2. `.env` file at the repo root (loaded by Pydantic Settings)
  3. Field defaults below
"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Server -----------------------------------------------------------
    api_host: str = Field(default="0.0.0.0", description="Bind address for the FastAPI server.")
    api_port: int = Field(default=8000, description="Bind port for the FastAPI server.")
    agent_auth_token: str = Field(
        default="",
        description=(
            "Bearer token required by chat routes. Empty = auth disabled "
            "(loud warning at startup)."
        ),
    )

    # --- Identity ---------------------------------------------------------
    agent_user_id: str = Field(default="me", description="Fixed user_id for memory scoping.")
    agent_working_directory: str | None = Field(
        default=None,
        description="Working dir baked into the system prompt; defaults to process cwd.",
    )

    # --- Memory / persistence --------------------------------------------
    memory_db_path: Path = Field(
        default=Path("data/agent.db"),
        description="SQLite file backing conversation history, facts, and summaries.",
    )
    summarizer_provider: str = Field(default="gemini", description="`gemini` or `local`.")
    summarizer_model: str | None = Field(default=None)
    summarizer_idle_minutes: int = Field(default=30)
    summarizer_base_url: str = Field(default="http://localhost:8080/v1")
    summarizer_api_key: str = Field(default="local")

    # --- Models / providers ----------------------------------------------
    gemini_api_key: str | None = Field(default=None)
    gemini_model: str = Field(default="gemini-2.5-flash")
    google_thinking_budget: int = Field(default=1000)

    # Local llama.cpp (OpenAI-compatible) endpoint.
    local_model_name: str = Field(default="gemma-4-26B")
    local_base_url: str = Field(default="http://localhost:8080/v1")
    local_api_key: str = Field(default="local")

    # --- Router (intent classifier) --------------------------------------
    router_provider: str = Field(default="gemini", description="`gemini` or `regex`.")
    router_model: str | None = Field(default=None, description="Defaults to gemini_model.")
    router_base_url: str = Field(default="http://localhost:8080/v1")
    router_api_key: str = Field(default="local")

    # --- MCP --------------------------------------------------------------
    mcp_server_url: str = Field(default="http://localhost:8081/mcp")
    github_personal_access_token: str | None = Field(default=None)
    github_mcp_url: str | None = Field(default=None)
    github_mcp_toolsets: str = Field(default="")
    logfire_read_token: str | None = Field(default=None)
    logfire_base_url: str = Field(default="https://logfire-eu.pydantic.dev")

    # --- Observability ----------------------------------------------------
    logfire_token: str | None = Field(default=None)


SETTINGS = Settings()
