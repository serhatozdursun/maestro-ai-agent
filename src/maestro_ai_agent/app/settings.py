"""Runtime settings loaded from the environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process settings. Values map to environment variables (e.g. LOG_LEVEL)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = "INFO"
    log_json: bool = False
