from urllib.parse import parse_qs, urlparse

import pytest

from duecare import auth
from duecare.config import settings

from .conftest import account

DEEP_LINK = "duecare://auth/callback"


@pytest.fixture
def mobile(monkeypatch):
    monkeypatch.setattr(settings(), "mobile_redirect_url", DEEP_LINK)


def bearer(handle):
    return {"authorization": "Bearer " + handle}


def test_mobile_sign_in_is_off_until_configured(client, monkeypatch):
    monkeypatch.setattr(settings(), "mobile_redirect_url", "")
    r = client.post("/api/v1/mobile/auth/start", json={})
    assert r.status_code == 503
    assert r.json()["code"] == "AUTH_CONFIGURATION"


def test_mobile_sign_in_returns_to_the_app_and_uses_a_bearer_session(client, student, mobile):
    start = client.post("/api/v1/mobile/auth/start", json={"consent": True}).json()
    query = parse_qs(urlparse(start["url"]).query)
    assert query["redirect_to"] == [DEEP_LINK]
    assert query["prompt"] == ["consent"]
    assert query["code_challenge_method"] == ["s256"]

    auth.provider.next_tokens = {"access_token": student.token, "refresh_token": "fresh"}
    callback = client.post("/api/v1/mobile/auth/callback", json={"state": start["state"], "code": "c"})
    assert callback.status_code == 200
    handle = callback.json()["session"]
    # The state is one-use: an intercepted deep link cannot be redeemed a second time.
    again = client.post("/api/v1/mobile/auth/callback", json={"state": start["state"], "code": "c"})
    assert again.status_code == 401

    me = client.get("/api/v1/me", headers=bearer(handle))
    assert me.status_code == 200
    assert me.json()["identity"]["id"] == str(student.uid)
    created = client.post(
        "/api/v1/tasks",
        headers={**bearer(handle), "idempotency-key": "mobile-1"},
        json={"title": "Lab record", "type": "assignment"},
    )
    assert created.status_code == 201

    assert client.post("/api/v1/mobile/auth/logout", headers=bearer(handle)).status_code == 200
    assert client.get("/api/v1/me", headers=bearer(handle)).status_code == 401


def test_bearer_and_gateway_requirements(client, student):
    # Without a bearer token the gateway secret is still required.
    assert (
        client.get("/api/v1/me", headers={"x-session": student.handle}).json()["code"] == "GATEWAY_REQUIRED"
    )
    assert client.get("/api/v1/me", headers=bearer("not-a-session")).json()["code"] == "SIGN_IN_REQUIRED"
    assert client.get("/api/v1/me", headers=bearer(" ")).status_code == 401
    # The web session handle and the gateway keep working unchanged.
    assert client.get("/api/v1/me", headers=student.headers).status_code == 200
    assert client.get("/api/v1/me", headers=bearer(student.handle)).status_code == 200
    # Another student's handle reaches only that student's data.
    other = account()
    assert client.get("/api/v1/me", headers=bearer(other.handle)).json()["id"] == str(other.uid)


def test_mobile_callback_validates_input(client, mobile):
    assert (
        client.post("/api/v1/mobile/auth/callback", json={"state": "x" * 101, "code": "c"}).status_code == 422
    )
    assert client.post("/api/v1/mobile/auth/callback", json={"state": "s"}).status_code == 422
    assert (
        client.post("/api/v1/mobile/auth/callback", json={"state": "unknown", "code": "c"}).status_code == 401
    )


def test_mobile_account_deletion_resumes_with_its_token(client, student):
    started = client.post(
        "/api/v1/privacy/account-deletion",
        headers={**bearer(student.handle), "idempotency-key": "delete-1"},
        json={"confirmation": "DELETE"},
    ).json()
    assert client.post("/api/v1/mobile/account-deletion", json={"token": "a" * 64}).status_code == 404
    progress = client.post("/api/v1/mobile/account-deletion", json={"token": started["resumeToken"]})
    assert progress.status_code == 200
    assert progress.json()["id"] == started["id"]
    assert "resumeToken" not in progress.json()
