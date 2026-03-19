from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    _env_path = Path(__file__).resolve().parent / ".env"
    model_config = SettingsConfigDict(env_file=str(_env_path), case_sensitive=False)

    supabase_url: str
    supabase_service_key: str
    gemini_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
