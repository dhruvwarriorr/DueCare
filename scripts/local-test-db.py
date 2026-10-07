"""Provision an isolated loopback-only test database; never targets hosted credentials."""

from pathlib import Path
import json, secrets, subprocess
import psycopg
from cryptography.fernet import Fernet

root = Path(__file__).resolve().parents[1]
with psycopg.connect("postgresql://postgres@127.0.0.1:55432/postgres", autocommit=True) as db:
    exists = db.execute("select 1 from pg_database where datname='duecare_test'").fetchone()
    if not exists:
        db.execute("create database duecare_test")
admin = "postgresql+psycopg://postgres@127.0.0.1:55432/duecare_test"
with psycopg.connect(admin.replace("+psycopg", ""), autocommit=True) as db:
    db.execute("create schema if not exists auth")
    db.execute(
        "create table if not exists auth.users (id uuid primary key,email text,email_confirmed_at timestamptz)"
    )
    db.execute(
        "create table if not exists auth.sessions (id uuid primary key,user_id uuid references auth.users)"
    )
    db.execute(
        "create table if not exists auth.identities (user_id uuid references auth.users,provider text,identity_data jsonb)"
    )
    for role in ("supabase_auth_admin", "anon", "authenticated"):
        db.execute(
            f"do $$ begin if not exists (select from pg_roles where rolname='{role}') then create role {role}; end if; end $$"
        )
    db.execute(
        "do $$ begin if not exists (select from pg_roles where rolname='duecare_test_app') then create role duecare_test_app login nosuperuser nobypassrls; end if; end $$"
    )
subprocess.run(
    ["uv", "run", "alembic", "upgrade", "head"],
    cwd=root / "apps/api",
    env={**__import__("os").environ, "MIGRATION_DATABASE_URL": admin},
    check=True,
)
with psycopg.connect(admin.replace("+psycopg", ""), autocommit=True) as db:
    db.execute("grant duecare_runtime to duecare_test_app")
    for table in ("users", "sessions", "identities"):
        db.execute("alter table auth." + table + " enable row level security")
    db.execute((root / "apps/api/sql/supabase_auth.sql").read_text())
config = {
    "DATABASE_URL": "postgresql+psycopg://duecare_test_app@127.0.0.1:55432/duecare_test",
    "MIGRATION_DATABASE_URL": admin,
    "GATEWAY_SECRET": secrets.token_urlsafe(48),
    "SESSION_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "SUPABASE_URL": "https://auth.example.test",
    "SUPABASE_PUBLISHABLE_KEY": "test-only",
    "WEB_ORIGIN": "http://localhost:3001",
    # Synthetic source settings: tests use a fake Google provider and never call Google.
    "GOOGLE_OAUTH_CLIENT_ID": "test-client.apps.googleusercontent.com",
    "GOOGLE_OAUTH_CLIENT_SECRET": "test-only",
    "SOURCE_TOKEN_KEYS": "v1:" + Fernet.generate_key().decode() + ",v2:" + Fernet.generate_key().decode(),
    "SOURCE_TOKEN_KEY_VERSION": "v2",
    "SYNC_WORK_BUDGET_SECONDS": "5",
    "ACADEMIC_SENDER_DOMAINS": "somaiya.edu",
    # Never reach real AI providers from tests, even if the developer's .env has keys.
    "GROQ_API_KEY": "",
    "GROQ_MODEL": "",
    "GROQ_FALLBACK_MODEL": "",
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "",
    "GEMINI_API_KEY": "",
    "GEMINI_MODEL": "",
    "AUTO_COMPLETION_PATHS": "",
    "LMS_SENDERS": "lms-kjsse@somaiya.edu",
    "LMS_HOSTS": "lms-kjsce.somaiya.edu",
}
(root / ".local").mkdir(exist_ok=True)
(root / ".local/test-config.json").write_text(json.dumps(config))
(root / ".local/test-config.json").chmod(0o600)
print("Isolated local test database provisioned and migrated.")
