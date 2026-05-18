from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    brave_api_key: str = ""
    brave_concurrency: int = 10
    fetch_concurrency: int = 10

    max_queries: int = 5

    data_dir: Path = Path("./data")
    database_url: str = "sqlite:///./data/index.db"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
