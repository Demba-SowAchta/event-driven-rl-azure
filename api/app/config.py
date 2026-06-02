"""Settings via env vars (zero secret committed)."""
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", protected_namespaces=()
    )
    model_path: str = "/app/artifacts/ppo_v1.0.0.pkl"
    model_version: str = "1.0.0"
    api_version: str = "1.0.0"
    api_title: str = "RL Trading Agent API"
    algo: str = "PPO"
    framework: str = "stable-baselines3"
    applicationinsights_connection_string: Optional[str] = None
    allowed_origins: List[str] = ["*"]


settings = Settings()
