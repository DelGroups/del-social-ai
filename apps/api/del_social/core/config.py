from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "info"
    database_url: str
    redis_url: str
    allowed_origins: str = ""

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
