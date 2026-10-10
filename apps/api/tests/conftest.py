import json
import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from duecare import auth, naming
from duecare.models import now

config = json.loads((Path(__file__).resolve().parents[3] / ".local/test-config.json").read_text())
os.environ.update(config)
from duecare.db import transaction  # noqa: E402 - configure isolated test environment before loading app
from duecare.main import app  # noqa: E402

KEY = ec.generate_private_key(ec.SECP256R1())


class FixtureAuth(auth.SupabaseAuth):
    def claims(self, token):
        return jwt.decode(
            token,
            KEY.public_key(),
            algorithms=["ES256"],
            audience="authenticated",
            issuer=config["SUPABASE_URL"] + "/auth/v1",
            options={"require": ["exp", "iat", "sub", "aud", "iss", "session_id"]},
        )

    def exchange(self, grant, payload):
        return self.next_tokens

    def logout(self, token):
        claims = self.claims(token)
        with create_engine(config["MIGRATION_DATABASE_URL"]).begin() as db:
            db.execute(text("delete from auth.sessions where id=:id"), {"id": claims["session_id"]})


def issue(uid, sid, seconds=3600):
    return jwt.encode(
        {
            "sub": str(uid),
            "session_id": str(sid),
            "iat": now(),
            "exp": now() + timedelta(seconds=seconds),
            "aud": "authenticated",
            "iss": config["SUPABASE_URL"] + "/auth/v1",
        },
        KEY,
        algorithm="ES256",
    )


def account(email="student@somaiya.edu", verified=True):
    uid, sid = uuid4(), uuid4()
    with create_engine(config["MIGRATION_DATABASE_URL"]).begin() as db:
        db.execute(text("insert into auth.users values (:id,:email,now())"), {"id": uid, "email": email})
        db.execute(text("insert into auth.sessions values (:id,:uid)"), {"id": sid, "uid": uid})
        db.execute(
            text("insert into auth.identities values (:id,'google',cast(:data as jsonb))"),
            {
                "id": uid,
                "data": json.dumps({"email": email, "email_verified": verified, "name": "Test Student"}),
            },
        )
    token = issue(uid, sid)
    from duecare.models import WebSession

    handle = __import__("secrets").token_urlsafe(32)
    with transaction() as db:
        db.add(
            WebSession(
                id=auth.digest(handle),
                user_id=uid,
                tokens=auth.crypt()
                .encrypt(json.dumps({"access_token": token, "refresh_token": "fixture-refresh"}).encode())
                .decode(),
            )
        )
        db.commit()
    return SimpleNamespace(
        uid=uid,
        sid=sid,
        token=token,
        handle=handle,
        headers={
            "x-gateway-secret": config["GATEWAY_SECRET"],
            "x-session": handle,
            "idempotency-key": str(uuid4()),
        },
    )


@pytest.fixture(autouse=True)
def fixture_provider(monkeypatch):
    monkeypatch.setattr(auth, "provider", FixtureAuth())


AI_NAME_TITLES = naming.name_titles


@pytest.fixture(autouse=True)
def offline_naming(monkeypatch):
    """Task naming never reaches a provider in tests; tests of the AI path restore AI_NAME_TITLES."""
    monkeypatch.setattr(
        naming, "name_titles", lambda items: ({i["key"]: naming.tidy(i["title"]) for i in items}, False)
    )


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def student():
    return account()


@pytest.fixture
def headers(student):
    class Headers(dict):
        def fresh(self):
            return {**self, "idempotency-key": str(uuid4())}

    return Headers(student.headers)
