from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # --- Solana / market data ---
    HELIUS_API_KEY: SecretStr = SecretStr("")
    HELIUS_WS_URL: str = ""
    HELIUS_RPC_URL: str = ""
    BIRDEYE_API_KEY: SecretStr = SecretStr("")
    RUGCHECK_JWT: SecretStr = SecretStr("")
    GMGN_SESSION_COOKIE: SecretStr = SecretStr("")
    CIELO_API_KEY: SecretStr = SecretStr("")

    # --- Social / news ---
    TWITTER_BEARER_TOKEN: SecretStr = SecretStr("")
    TWITTER_SCRAPE_ACCOUNTS: str = ""
    NEWSAPI_KEY: SecretStr = SecretStr("")

    # --- AI providers ---
    ANTHROPIC_API_KEY: SecretStr = SecretStr("")
    OPENAI_API_KEY: SecretStr = SecretStr("")
    GROQ_API_KEY: SecretStr = SecretStr("")
    GOOGLE_AI_API_KEY: SecretStr = SecretStr("")
    OLLAMA_URL: str = "http://host.docker.internal:11434"

    # --- Infrastructure ---
    POSTGRES_URL: str = "postgresql+asyncpg://memeterm:memeterm@127.0.0.1:5432/memeterm"
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    CHROMA_URL: str = "http://127.0.0.1:8001"

    # --- App ---
    PHANTOM_PUBKEY: str = ""
    DAILY_AI_BUDGET_USD: float = Field(default=15.00, ge=0)
    APP_BEARER_TOKEN: SecretStr = SecretStr("")
    LOG_LEVEL: str = "INFO"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = Field(default=8787, ge=1, le=65535)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
