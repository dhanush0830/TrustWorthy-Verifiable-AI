"""Configuration settings for Trustworthy and Verifiable AI backend."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable overrides."""
    
    PROJECT_NAME: str = "Trustworthy and Verifiable AI"
    PACKAGE_NAME: str = "trustworthy_verifiable_ai"
    API_V1_STR: str = "/api/v1"
    
    # Security
    SECRET_KEY: str = "dev-secret-key-change-in-production-32bytesmin"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day
    
    # Currency configuration (Fixed to USD minor units)
    DEFAULT_CURRENCY: str = "USD"
    
    # Database
    DATABASE_PATH: Path = Path(__file__).resolve().parents[2] / "trustworthy_ai.db"
    
    # LLM / Provider Configuration
    LLM_PROVIDER: str = "auto"  # "auto", "sarvam", "ollama", "mock"
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"
    OLLAMA_TIMEOUT_SECONDS: float = 60.0
    LLM_TEMPERATURE: float = 0.0
    LLM_PROMPT_VERSION: str = "2026-10-phase2-v1"
    MAX_COMPLAINT_CHARS: int = 4000
    
    # Sarvam AI Configuration (read strictly through environment / ignored .env)
    SARVAM_API_KEY: str | None = None
    SARVAM_BASE_URL: str = "https://api.sarvam.ai"
    SARVAM_MODEL: str = "sarvam-105b"
    SARVAM_TIMEOUT_SECONDS: float = 60.0
    
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Return the SQLite database URL."""
        return f"sqlite:///{self.DATABASE_PATH.as_posix()}"

    # Determine candidate .env locations across workspace, repo, and backend
    _THIS_PATH = Path(__file__).resolve()
    _ENV_CANDIDATES = tuple(
        str(p / ".env") for p in [
            _THIS_PATH.parents[5] if len(_THIS_PATH.parents) > 5 else None,  # Workspace root (e.g. C:\TrustWirthy ai)
            _THIS_PATH.parents[4] if len(_THIS_PATH.parents) > 4 else None,  # Repo root
            _THIS_PATH.parents[2] if len(_THIS_PATH.parents) > 2 else None,  # Backend root
        ] if p is not None
    ) + (".env", "../.env")

    model_config = SettingsConfigDict(
        env_file=_ENV_CANDIDATES,
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
