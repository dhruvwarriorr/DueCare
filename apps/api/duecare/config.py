from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = ""
    migration_database_url: str = ""
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    gateway_secret: str = ""
    session_encryption_key: str = ""
    web_origin: str = "http://localhost:3000"


@lru_cache
def settings():
    return Settings()
