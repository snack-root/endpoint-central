from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_NAME: str = "Endpoint Central"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = (
        "postgresql+asyncpg://ec_user:ec_pass@localhost:5432/endpoint_central"
    )

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Security
    SECRET_KEY: str = "changeme-in-production"
    SESSION_COOKIE_NAME: str = "ec_session"
    SESSION_MAX_AGE: int = 60 * 60 * 8  # 8 hours

    # Agent Gateway
    GATEWAY_API_KEY: str = "dev-gateway-key"

    # AI / Ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"

    # File uploads
    UPLOAD_DIR: str = "/app/uploads"
    MAX_UPLOAD_SIZE: int = 500 * 1024 * 1024  # 500 MB

    # Monitoring
    HEARTBEAT_TIMEOUT_SECONDS: int = 120  # device offline after 2 missed heartbeats


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
