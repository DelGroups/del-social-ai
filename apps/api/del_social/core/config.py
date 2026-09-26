from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "info"
    database_url: str
    redis_url: str
    allowed_origins: str = ""
    app_base_url: str = "http://localhost:3000"  # panel URL used in invitation/reset links

    secret_key: str = ""  # signs public media URLs (and future server-side tokens)

    # Media library (docs/phase-1-plan.md §3): local volume, public signed URLs on the API domain
    media_root: str = "/data/media"
    media_public_url: str = "http://localhost:8000"  # https://api.del-groups.com in production

    # Channel connections (ADR 003). Empty = that feature is shown as "not configured".
    token_vault_key: str = ""  # 32 random bytes, hex or base64: openssl rand -hex 32
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_graph_version: str = "v23.0"
    meta_login_config_id: str = ""  # set when the app uses "Facebook Login for Business"

    # LLMs (docs/phase-1-plan.md §4, §9). Model ids are config, not code.
    anthropic_api_key: str = ""
    claude_model_fast: str = "claude-haiku-4-5-20251001"  # classify, first-pass checks
    claude_model_default: str = "claude-sonnet-5"  # most agents
    claude_model_strategy: str = "claude-opus-5-5"  # weekly planning
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    @property
    def langfuse_configured(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def meta_configured(self) -> bool:
        return bool(self.meta_app_id and self.meta_app_secret)

    @property
    def asyncpg_dsn(self) -> str:
        # SQLAlchemy-style "postgresql+asyncpg://" → plain DSN for asyncpg
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
