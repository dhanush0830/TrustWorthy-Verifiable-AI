import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable overrides."""
    
    PROJECT_NAME: str = "Trustworthy and Verifiable AI"
    PACKAGE_NAME: str = "trustworthy_verifiable_ai"
    API_V1_STR: str = "/api/v1"
    
    # Environment & Security
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "dev-secret-key-change-in-production-32bytesmin"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day
    
    # CORS (Configurable for local dev and deployed frontend origin)
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return ["http://localhost:3000", "http://127.0.0.1:3000"]
            if v.startswith("[") and v.endswith("]"):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(item).strip().rstrip("/") for item in parsed if str(item).strip()]
                except Exception:
                    pass
            return [origin.strip().rstrip("/") for origin in v.split(",") if origin.strip()]
        elif isinstance(v, (list, tuple)):
            return [str(origin).strip().rstrip("/") for origin in v if str(origin).strip()]
        return ["http://localhost:3000", "http://127.0.0.1:3000"]

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str, info) -> str:
        env = info.data.get("ENVIRONMENT", "development")
        if env == "production" and v == "dev-secret-key-change-in-production-32bytesmin":
            raise ValueError(
                "In production, SECRET_KEY must be set to a secure random string via environment variable."
            )
        return v
    
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
