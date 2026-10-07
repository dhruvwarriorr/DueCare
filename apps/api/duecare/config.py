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
    # Phase 3 interpretation. Model IDs are deployment configuration, never hard-coded.
    # Provider order: Groq, then the Groq fallback model, then OpenAI, then Gemini (when configured).
    groq_api_key: str = ""
    groq_model: str = ""
    groq_fallback_model: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    gemini_api_key: str = ""
    gemini_model: str = ""
    ai_timeout_seconds: float = 45
    # Recognized college LMS notification sender(s) and activity hosts for template parsing.
    # The college LMS sender is the same for every Somaiya student.
    lms_senders: str = "lms-kjsse@somaiya.edu"
    lms_hosts: str = "lms-kjsce.somaiya.edu"
    # Automatic completion is enabled per validated path only after live checks pass:
    # lms_assignment_receipt, classroom_turned_in. Otherwise evidence asks the student to confirm.
    auto_completion_paths: str = ""


@lru_cache
def settings():
    return Settings()
