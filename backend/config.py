"""Application settings loaded from environment/.env via pydantic-settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_model_fast: str = "gpt-5.4-mini"
    openai_model_smart: str = "gpt-5.5"
    fhir_base_url: str = ""
    database_url: str = "sqlite+aiosqlite:///./anamnesis.db"
    log_level: str = "INFO"
    stage2_cache: bool = True
    stage2_max_concurrent: int = 50
    openai_regional_endpoint: bool = False
    price_table_path: str | None = None
    telemetry_jsonl_dir: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
