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
    
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Return the SQLite database URL."""
        return f"sqlite:///{self.DATABASE_PATH.as_posix()}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
