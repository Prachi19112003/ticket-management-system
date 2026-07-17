from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    ENV: Literal["local", "staging", "production"] = "local"
    DEBUG: bool = True

    # Database Settings
    POSTGRES_DB: str = "ticket_db"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ticket_db"

    # Redis Settings
    REDIS_URL: str = "redis://localhost:6379/0"

    # AWS / MinIO S3 Settings
    AWS_ACCESS_KEY_ID: str = "minioadmin"
    AWS_SECRET_ACCESS_KEY: str = "minioadmin"
    AWS_S3_BUCKET: str = "ticket-attachments"
    AWS_S3_ENDPOINT_URL: str = "http://localhost:9000"

    # API Keys / Integrations
    OPENROUTER_API_KEY: str
    OPENROUTER_MODEL: str = "anthropic/claude-sonnet-4.5"

    # CC List mappings for category-based routing.
    # Note: The emails listed here are PLACEHOLDER values to be replaced with real addresses later.
    CC_MAPPING: dict[str, list[str]] = {
        "Sales": ["sales-placeholder@example.com"],
        "Procurement": ["procurement-placeholder@example.com"],
        "General": []
    }


    # Gmail OAuth2 Settings
    GMAIL_CLIENT_ID: str = "mock-client-id"
    GMAIL_CLIENT_SECRET: str = "mock-client-secret"
    GMAIL_REFRESH_TOKEN: str = "mock-refresh-token"

    # Similarity threshold for RAG write-back (0.0 to 1.0)
    EDIT_DISTANCE_WRITEBACK_THRESHOLD: float = 0.85

    # SLA and tuning parameters
    LLM_TIMEOUT_SECONDS: float = 45.0
    THREAD_SUMMARY_TTL_SECONDS: int = 604800
    CLASSIFICATION_TEMPERATURE: float = 0.05

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
