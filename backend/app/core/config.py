from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Local Knowledge Base"
    database_path: Path = Path("./data/knowledge_base.db")
    upload_dir: Path = Path("./data/uploads")

    embedding_provider: str = "hash"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dimension: int = 384

    llm_provider: str = "openai_compatible"
    llm_base_url: str = "http://127.0.0.1:8642/v1"
    llm_api_key: str = "change-me-local-dev"
    llm_model: str = "hermes-agent"
    llm_timeout_seconds: int = 120

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    def ensure_dirs(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
