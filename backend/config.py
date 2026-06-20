"""Application settings loaded from environment/.env via pydantic-settings."""
import os

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str = ""
    umls_api_key: str = ""
    gemini_model_fast: str = "gemini-3.5-flash"
    gemini_model_smart: str = "gemini-3.5-flash"
    gemini_model_nano: str = "gemini-3.1-flash-lite"
    doc_guardrail_enabled: bool = True
    database_url: str = "sqlite+aiosqlite:///./anamnesis.db"
    log_level: str = "INFO"
    stage2_cache: bool = True
    stage2_max_concurrent: int = 50
    # Public origin where the in-host React UI assets (review.js/review.css) are
    # served from. PO's iframe is sandboxed (null origin), so the ui:// shell must
    # load assets over an absolute URL. Explicit env wins; else Render's injected
    # RENDER_EXTERNAL_URL (prod); else localhost (dev). Resolved in the validator.
    app_assets_base_url: str = ""
    # "api" = live terminology APIs (default); "faiss" = graduated local index path.
    coding_retriever: str = "api"
    warmup_coding_on_startup: bool = False
    # PO token verification (resource-server pillar). Per-user writes (config,
    # future BYOK secrets) require a PO-signed token; reads stay host-delegated.
    po_issuer: str = "https://app.promptopinion.ai/"
    po_jwks_uri: str = "https://app.promptopinion.ai/.well-known/jwks"
    po_mcp_id: str = ""  # optional pseudo-audience; empty = skip the check
    verify_config_writes: bool = True
    # L2a profile $validate (CONFORMANCE.md). When True, refuse to write a resource
    # the target FHIR server's $validate rejects (hard-gate). Default soft: validate
    # opportunistically and attach the result, but never block the write.
    validate_before_write: bool = False
    # Fernet key for encrypting BYOK secrets in app_user.config at rest. Empty =
    # BYOK disabled (storing a secret raises; the pipeline uses the server key).
    config_secret_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _resolve_assets_base_url(self) -> "Settings":
        if not self.app_assets_base_url:
            self.app_assets_base_url = (
                os.environ.get("RENDER_EXTERNAL_URL") or "http://localhost:8042"
            )
        return self


settings = Settings()
