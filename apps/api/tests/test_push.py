import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text

from duecare import activity, push
from duecare.db import transaction
from duecare.models import NotificationSettings, PushDevice, now

TOKEN = "fcm-token-" + "x" * 40


class FakeFcm:
    def __init__(self):
        self.sent = []
        self.outcome = "sent"

    def send(self, token, data, urgent):
        self.sent.append((token, data, urgent))
        return self.outcome(token) if callable(self.outcome) else self.outcome


@pytest.fixture
def fcm(monkeypatch):
    fake = FakeFcm()
    monkeypatch.setattr(push, "client", lambda: fake)
    return fake


@pytest.fixture
def later(monkeypatch):
    """Move push's clock past the settle window, as the worker would see it a little later."""
    monkeypatch.setattr(push, "now", lambda: now() + timedelta(minutes=5))


def pending(uid):
    with transaction() as db:
        rows = db.execute(text("select kind, owner_id from duecare_internal.pending_background_jobs()")).all()
    return [kind for kind, owner in rows if str(owner) == str(uid)]


def add_task(client, headers, title="Lab record"):
    r = client.post("/api/v1/tasks", headers=headers.fresh(), json={"title": title, "type": "assignment"})
    assert r.status_code == 201
    return r.json()


def source_event(uid, kind="new_task"):
    """An event from an import, as interpretation records it (not the student's own change)."""
    with transaction(uid) as db:
        activity.notify(
            db, uid, kind, "task", uuid4(), "New work was added to your tasks.", f"{uuid4()}:{kind}"
        )
        db.commit()


def register(client, headers, token=TOKEN):
    return client.post("/api/v1/devices", headers=headers.fresh(), json={"token": token})


def state(uid):
    with transaction(uid) as db:
        return db.get(NotificationSettings, uid)


def test_settings_defaults_validation_and_revisions(client, headers):
    first = client.get("/api/v1/notification-settings", headers=headers).json()
    assert first["revision"] is None
    assert first["settings"]["reminderLeads"] == [1440, 60]
    assert first["settings"]["quietHours"] is False
    assert first["push"] == {"configured": False, "devices": 0}

    chosen = {
        **first["settings"],
        "newWork": False,
        "reminderLeads": [60, 1440, 30, 60],
        "digest": True,
        "digestTime": "07:30",
    }
    saved = client.put("/api/v1/notification-settings", headers=headers.fresh(), json={"settings": chosen})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["settings"]["newWork"] is False
    assert body["settings"]["reminderLeads"] == [1440, 60, 30]  # Unique, furthest first.
    assert body["revision"] == 1

    stale = client.put(
        "/api/v1/notification-settings", headers=headers.fresh(), json={"revision": 7, "settings": chosen}
    )
    assert stale.status_code == 409
    again = client.put(
        "/api/v1/notification-settings",
        headers=headers.fresh(),
        json={"revision": 1, "settings": {**chosen, "push": False}},
    )
    assert again.json()["revision"] == 2

    for bad in (
        {"reminderLeads": [45]},
        {"reminderLeads": []},
        {"digestTime": "25:00"},
        {"quietStart": "7pm"},
    ):
        r = client.put(
            "/api/v1/notification-settings",
            headers=headers.fresh(),
            json={"revision": 2, "settings": {**chosen, **bad}},
        )
        assert r.status_code == 422, bad


def test_devices_register_once_and_unregister(client, headers, student):
    assert register(client, headers).json() == {"ok": True, "configured": False}
    assert register(client, headers).status_code == 200
    assert client.get("/api/v1/notification-settings", headers=headers).json()["push"]["devices"] == 1
    assert register(client, headers, token="short").status_code == 422
    # Registering starts the cursor now: earlier activity is never pushed.
    assert state(student.uid).pushed_through > now() - timedelta(minutes=1)
    assert pending(student.uid) == []
    client.post("/api/v1/devices/unregister", headers=headers.fresh(), json={"token": TOKEN})
    assert client.get("/api/v1/notification-settings", headers=headers).json()["push"]["devices"] == 0


def test_new_work_is_pushed_once_after_it_settles(client, headers, student, fcm, monkeypatch):
    register(client, headers)
    source_event(student.uid)
    source_event(student.uid)
    add_task(client, headers)  # The student's own task is not announced back to them.
    assert pending(student.uid) == ["push"]
    # A burst is still arriving: hold it.
    assert push.deliver(student.uid) is False
    assert fcm.sent == []
    monkeypatch.setattr(push, "now", lambda: now() + timedelta(minutes=5))
    assert push.deliver(student.uid) is True
    [(token, data, urgent)] = fcm.sent
    assert token == TOKEN and urgent is True
    assert data["type"] == "activity"
    assert data["kinds"] == "new_task:2"
    assert data["u"] == push.owner_hash(student.uid)
    # Content-free: no titles leave the server.
    assert "Lab record" not in json.dumps(data)
    assert pending(student.uid) == []


def test_disabled_categories_send_a_silent_refresh(client, headers, student, fcm, later):
    register(client, headers)
    settings = client.get("/api/v1/notification-settings", headers=headers).json()
    client.put(
        "/api/v1/notification-settings",
        headers=headers.fresh(),
        json={"revision": settings["revision"], "settings": {**settings["settings"], "newWork": False}},
    )
    source_event(student.uid)
    assert push.deliver(student.uid) is True
    [(_, data, urgent)] = fcm.sent
    assert (data["type"], data["kinds"], urgent) == ("refresh", "", False)


def test_the_students_own_changes_only_refresh_the_phone(client, headers, student, fcm, later):
    register(client, headers)
    task = add_task(client, headers)
    client.patch(
        f"/api/v1/tasks/{task['id']}", headers=headers.fresh(), json={"revision": 1, "status": "completed"}
    )
    assert push.deliver(student.uid) is True
    [(_, data, urgent)] = fcm.sent
    assert (data["type"], urgent) == ("refresh", False)
    items = client.get("/api/v1/activity", headers=headers).json()["items"]
    assert items and all(item["byStudent"] for item in items)


def test_deleting_work_refreshes_the_phone(client, headers, student, fcm, later):
    task = add_task(client, headers)
    register(client, headers)
    assert pending(student.uid) == []
    client.delete(f"/api/v1/tasks/{task['id']}?revision={task['revision']}", headers=headers.fresh())
    assert pending(student.uid) == ["push"]
    assert push.deliver(student.uid) is True
    assert fcm.sent[0][1]["type"] == "refresh"
    assert pending(student.uid) == []


def test_unregistered_tokens_are_forgotten_and_outages_retry(client, headers, student, fcm, later):
    register(client, headers)
    register(client, headers, token="gone-" + "y" * 40)
    fcm.outcome = lambda token: "invalid" if token.startswith("gone-") else "retry"
    source_event(student.uid)
    assert push.deliver(student.uid) is False
    with transaction(student.uid) as db:
        tokens = [d.token for d in db.query(PushDevice).filter(PushDevice.user_id == student.uid)]
    assert tokens == [TOKEN]
    held = state(student.uid)
    assert held.retry_at is not None
    assert held.pushed_through < now()
    assert pending(student.uid) == []  # Backing off.
    fcm.outcome = "sent"
    with transaction(student.uid) as db:
        db.get(NotificationSettings, student.uid).retry_at = None
        db.commit()
    assert push.deliver(student.uid) is True
    assert fcm.sent[-1][1]["kinds"] == "new_task:1"


def test_push_is_skipped_without_devices_or_configuration(client, headers, student, monkeypatch, later):
    register(client, headers)
    monkeypatch.setattr(push, "client", lambda: None)
    add_task(client, headers)
    assert push.deliver(student.uid) is True
    assert pending(student.uid) == []
    r = client.post("/api/v1/devices/test", headers=headers.fresh())
    assert (r.status_code, r.json()["code"]) == (503, "PUSH_CONFIGURATION")


def test_test_notification(client, headers, student, fcm):
    r = client.post("/api/v1/devices/test", headers=headers.fresh())
    assert (r.status_code, r.json()["code"]) == (409, "NO_DEVICE")
    register(client, headers)
    assert client.post("/api/v1/devices/test", headers=headers.fresh()).json() == {"sent": 1, "failed": 0}
    assert fcm.sent[0][1]["type"] == "test"


def test_auto_completion_from_a_source_is_an_activity():
    added = []
    db = SimpleNamespace(scalar=lambda *_: None, add=added.append)
    task = SimpleNamespace(user_id=uuid4(), id=uuid4())
    activity.task_changed(db, task, "completed", {"status": "completed"}, SimpleNamespace(id=uuid4()))
    assert added[0].event_type == "auto_completed"
    activity.task_changed(db, task, "completed", {"status": "completed"})  # The student's own tap.
    assert len(added) == 1


def test_fcm_client_signs_in_and_classifies_answers(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    account = {
        "project_id": "duecare-test",
        "client_email": "push@duecare-test.iam",
        "private_key": pem.decode(),
    }
    calls = []

    def post(url, **kw):
        calls.append((url, kw))
        if url.endswith("/token"):
            claims = jwt.decode(
                kw["data"]["assertion"], key.public_key(), algorithms=["RS256"], audience=kw and url
            )
            assert claims["scope"] == push.Fcm.scope
            return httpx.Response(
                200, json={"access_token": "at-1", "expires_in": 3600}, request=httpx.Request("POST", url)
            )
        token = kw["json"]["message"]["token"]
        status = {"ok": 200, "gone": 404, "busy": 503}[token]
        body = {"error": {"status": "UNREGISTERED"}} if token == "gone" else {}
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(push.httpx, "post", post)
    fcm = push.Fcm(account)
    assert fcm.send("ok", {"type": "test"}, urgent=True) == "sent"
    assert fcm.send("gone", {"type": "test"}, urgent=False) == "invalid"
    assert fcm.send("busy", {"type": "test"}, urgent=False) == "retry"
    sends = [kw for url, kw in calls if "messages:send" in url]
    assert sends[0]["headers"]["Authorization"] == "Bearer at-1"
    assert sends[0]["json"]["message"]["android"]["priority"] == "high"
    assert sends[1]["json"]["message"]["android"]["priority"] == "normal"
    # The access token is reused until it nears expiry.
    assert len([url for url, _ in calls if url.endswith("/token")]) == 1
