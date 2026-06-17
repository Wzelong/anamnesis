"""Application settings loaded from environment/.env via pydantic-settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str = ""
    umls_api_key: str = ""
    openai_model_fast: str = "gpt-5.4-mini"
    openai_model_smart: str = "gpt-5.5"
    openai_model_nano: str = "gpt-5.4-nano"
    doc_guardrail_enabled: bool = True
    database_url: str = "sqlite+aiosqlite:///./anamnesis.db"
    log_level: str = "INFO"
    stage2_cache: bool = True
    stage2_max_concurrent: int = 50
    frontend_base_url: str = "http://localhost:3042"
    # Public origin where the in-host React UI assets (review.js/review.css) are
    # served from. PO's iframe is sandboxed (null origin), so the ui:// shell must
    # load assets over an absolute URL — the ngrok/public host of this server.
    app_assets_base_url: str = "http://localhost:8042"
    # "api" = live terminology APIs (default); "faiss" = graduated local index path.
    coding_retriever: str = "api"
    warmup_coding_on_startup: bool = False
    # Expose the legacy DB-backed MCP tools (PHI-persisting). Off by default;
    # enable for the standalone web-workspace deployment.
    expose_legacy_tools: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
