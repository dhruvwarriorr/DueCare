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
    # Source authorization: one Google OAuth web client, separate from Supabase login.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    # Comma-separated "version:fernet-key" pairs; the current version encrypts new tokens.
    source_token_keys: str = ""
    source_token_key_version: str = ""
    sync_work_budget_seconds: float = 90
    google_request_timeout_seconds: float = 15
    academic_sender_domains: str = "somaiya.edu"


@lru_cache
def settings():
    return Settings()
