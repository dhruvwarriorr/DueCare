from datetime import timedelta
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

GMAIL_LOOKBACK = timedelta(days=30)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = ""
    migration_database_url: str = ""
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    gateway_secret: str = ""
    session_encryption_key: str = ""
    web_origin: str = "http://localhost:3000"
    # Where Supabase returns the mobile app after Google sign-in (an app deep link). Empty turns
    # mobile sign-in off. It must also be on Supabase's Auth redirect allowlist.
    mobile_redirect_url: str = ""
    background_worker_mode: Literal["embedded", "external"] = "embedded"
    worker_dispatch_secret: str = ""
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
    # Provider order: OpenRouter, Groq, the Groq fallback model, OpenAI, Gemini (when configured).
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    openrouter_concurrency: int = Field(default=10, ge=1, le=10)
    openrouter_max_output_tokens: int = Field(default=8192, ge=1024, le=32768)
    openrouter_reasoning_effort: str = "low"
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
    # Verified LMS assignment/quiz receipts always complete their exact task.
    # The connected student's Classroom TURNED_IN state also completes matching work.
    auto_completion_paths: str = ""


@lru_cache
def settings():
    return Settings()
