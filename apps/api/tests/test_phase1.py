import json
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from duecare import auth
from duecare.db import transaction
from duecare.models import Task, WebSession, now
from tests.conftest import KEY, account, config, issue

PROFILE = {
    "institution": "Example University",
    "programme": "Engineering",
    "department": "Computing",
    "admissionYear": 2025,
    "classYear": "SY",
    "currentSemester": 3,
    "division": "B",
    "generalBatch": "2",
    "rollNumber": "001A",
}


def test_profile_required_fields_batch_and_conflicts(client, headers):
    p = client.get("/api/v1/me", headers=headers).json()
    assert not p["onboardingComplete"]
    p = client.patch("/api/v1/me", headers=headers, json={**PROFILE, "revision": p["revision"]}).json()
    assert p["onboardingComplete"] and p["rollNumber"] == "001A"
    assert (
        client.patch("/api/v1/me", headers=headers, json={"revision": 1, "division": "A"}).status_code == 409
    )
    assert (
        client.patch(
            "/api/v1/me", headers=headers, json={"revision": p["revision"], "generalBatch": None}
        ).status_code
        == 422
    )
    s = client.post(
        "/api/v1/subjects", headers=headers, json={"name": "Database", "kind": "lab", "batch": "3"}
    )
    assert s.status_code == 422


@pytest.mark.parametrize(
    "email,verified,expected",
    [
        ("outsider@gmail.com", True, 403),
        ("student@somaiya.edu", False, 403),
        ("x@somaiya.edu.attacker.test", True, 403),
    ],
)
def test_ineligible_native_identity(client, email, verified, expected):
    a = account(email, verified)
    assert client.get("/api/v1/me", headers=a.headers).status_code == expected


def test_gateway_and_revoked_session(client, headers, student):
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers={**headers, "x-gateway-secret": "wrong"}).status_code == 401
    with create_engine(config["MIGRATION_DATABASE_URL"]).begin() as db:
        db.execute(text("delete from auth.sessions where id=:id"), {"id": student.sid})
    assert client.get("/api/v1/me", headers=headers).json()["code"] == "SESSION_REVOKED"


def test_unreadable_session_requires_sign_in(client, headers, student):
    from cryptography.fernet import Fernet

    # An environment override or old encryption key must not trap the UI in a 500 retry loop.
    with transaction() as db:
        entry = db.get(WebSession, auth.digest(student.handle))
        entry.tokens = Fernet(Fernet.generate_key()).encrypt(b"private session tokens").decode()
        db.commit()

    response = client.get("/api/v1/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == "SIGN_IN_REQUIRED"
    assert "private session tokens" not in response.text
    assert client.get("/api/v1/me", headers=account().headers).status_code == 200


def test_owned_resources_rls_foreign_keys(client, headers, student):
    other = account()
    s = client.post("/api/v1/subjects", headers=headers, json={"name": "Private lab", "kind": "lab"}).json()
    t = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Private task", "type": "assignment", "subjectId": s["id"]},
    ).json()
    for path in [
        "/tasks/" + t["id"],
        "/tasks/" + t["id"] + "/history",
        "/subjects/" + s["id"],
        "/subjects/" + s["id"] + "/timetable",
    ]:
        assert client.get("/api/v1" + path, headers=other.headers).status_code == 404
    assert (
        client.post(
            "/api/v1/tasks",
            headers=other.headers,
            json={"title": "Wrong association", "type": "test", "subjectId": s["id"]},
        ).status_code
        == 404
    )
    assert (
        client.patch(
            "/api/v1/tasks/" + t["id"], headers=other.headers, json={"revision": 1, "title": "Attack"}
        ).status_code
        == 404
    )
    assert client.delete("/api/v1/tasks/" + t["id"] + "?revision=1", headers=other.headers).status_code == 404
    with transaction(other.uid) as db:
        assert db.get(Task, t["id"]) is None
        from sqlalchemy.exc import ProgrammingError

        with pytest.raises(ProgrammingError):
            db.execute(
                text(
                    "insert into duecare.tasks (id,user_id,title,type,status,data,revision,created_at,updated_at) values (:id,:uid,'bad','test','due','{}',1,now(),now())"
                ),
                {"id": uuid4(), "uid": student.uid},
            )
        db.rollback()


@pytest.mark.parametrize("kind,expected", [("assignment", "overdue"), ("test", "missed")])
def test_status_completion_survives_edits_and_reopening(client, headers, kind, expected):
    t = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Work", "type": kind, "dueAt": (now() - timedelta(hours=1)).isoformat()},
    ).json()
    assert t["status"] == expected
    t = client.patch(
        "/api/v1/tasks/" + t["id"],
        headers=headers.fresh(),
        json={"revision": t["revision"], "status": "completed"},
    ).json()
    assert t["status"] == "completed" and t["completionOrigin"] == "manual"
    t = client.patch(
        "/api/v1/tasks/" + t["id"],
        headers=headers.fresh(),
        json={"revision": t["revision"], "notes": "Keep my completion"},
    ).json()
    assert t["status"] == "completed"
    t = client.patch(
        "/api/v1/tasks/" + t["id"], headers=headers.fresh(), json={"revision": t["revision"], "status": "due"}
    ).json()
    assert t["status"] == expected
    h = client.get("/api/v1/tasks/" + t["id"] + "/history", headers=headers).json()["items"]
    assert {"created", "completed", "edited", "reopened"} <= {e["action"] for e in h}


def test_quiz_window_fixed_session_and_date_only(client, headers):
    close = now() + timedelta(hours=1)
    q = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "Quiz",
            "type": "test",
            "timingMode": "attempt_window",
            "availabilityOpensAt": (now() - timedelta(hours=1)).isoformat(),
            "availabilityClosesAt": close.isoformat(),
        },
    ).json()
    assert q["status"] == "due" and q["dueAt"] == close.isoformat()
    q = client.patch(
        "/api/v1/tasks/" + q["id"],
        headers=headers.fresh(),
        json={"revision": 1, "availabilityClosesAt": (now() - timedelta(minutes=1)).isoformat()},
    ).json()
    assert q["status"] == "missed"
    history = client.get("/api/v1/tasks/" + q["id"] + "/history", headers=headers).json()["items"]
    assert history[0]["changes"]["dueAt"] == q["dueAt"]
    assert history[0]["changes"]["status"] == "missed"
    a = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Date", "type": "assignment", "dueDate": "2026-10-20"},
    ).json()
    assert (
        a["dueAt"].startswith("2026-10-20T18:29")
        and a["timingProvenance"]["dueAt"]["defaultTime"] == "23:59 IST"
    )
    t = client.post(
        "/api/v1/tasks", headers=headers, json={"title": "Date", "type": "test", "dueDate": "2026-10-20"}
    ).json()
    assert t["dueAt"] is None and t["status"] == "due"
    invalid = [
        {"timingMode": "fixed_session"},
        {"dueAt": "2026-01-01T12:00:00"},
        {"startsAt": close.isoformat(), "endsAt": (close - timedelta(minutes=1)).isoformat()},
    ]
    for fields in invalid:
        assert (
            client.post(
                "/api/v1/tasks", headers=headers, json={"title": "Bad", "type": "test", **fields}
            ).status_code
            == 422
        )


def test_timetable_atomic_replace_and_revision(client, headers):
    client.get("/api/v1/me", headers=headers)
    client.patch("/api/v1/me", headers=headers, json={"revision": 1, **PROFILE})
    s = client.post(
        "/api/v1/subjects", headers=headers, json={"name": "Math tutorial", "kind": "tutorial"}
    ).json()
    path = "/api/v1/subjects/" + s["id"] + "/timetable"
    slot = {
        "weekday": 1,
        "startTime": "14:00",
        "endTime": "16:00",
        "validFrom": "2026-07-01",
        "validUntil": "2026-11-30",
    }
    result = client.put(path, headers=headers, json={"revision": 1, "slots": [slot]})
    assert result.status_code == 200
    body = result.json()
    assert body["slots"][0]["semesterContext"] == 3
    replay = client.put(path, headers=headers, json={"revision": 1, "slots": [slot]})
    assert replay.json() == body
    assert client.put(path, headers=headers.fresh(), json={"revision": 1, "slots": []}).status_code == 409
    assert (
        client.put(
            path, headers=headers.fresh(), json={"revision": 2, "slots": [{**slot, "endTime": "13:00"}]}
        ).status_code
        == 422
    )
    result = client.put(path, headers=headers.fresh(), json={"revision": 2, "slots": []})
    assert result.json()["slots"] == []


def test_pagination_filters_history_delete_and_subject_unlink(client, headers):
    s = client.post(
        "/api/v1/subjects", headers=headers, json={"name": "Data theory", "kind": "theory"}
    ).json()
    for i in range(3):
        client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"title": f"Paginated {i}", "type": "assignment", "subjectId": s["id"]},
        )
    p = client.get("/api/v1/tasks?q=Paginated&limit=2", headers=headers).json()
    assert len(p["items"]) == 2 and p["nextCursor"]
    p2 = client.get("/api/v1/tasks?q=Paginated&limit=2&cursor=" + p["nextCursor"], headers=headers).json()
    assert len(p2["items"]) == 1 and not set(t["id"] for t in p["items"]) & set(t["id"] for t in p2["items"])
    assert client.get("/api/v1/tasks?limit=101", headers=headers).status_code == 422
    assert (
        len(client.get("/api/v1/tasks?subjectKind=theory&priority=low", headers=headers).json()["items"]) == 3
    )
    t = p["items"][0]
    assert (
        client.delete("/api/v1/subjects/" + s["id"] + "?revision=1", headers=headers.fresh()).status_code
        == 200
    )
    t = client.get("/api/v1/tasks/" + t["id"], headers=headers).json()
    assert t["subjectId"] is None
    path = "/api/v1/tasks/" + t["id"] + "?revision=" + str(t["revision"])
    fresh = headers.fresh()
    assert client.delete(path, headers=fresh).status_code == 200
    assert client.delete(path, headers=fresh).status_code == 200
    assert client.get("/api/v1/tasks/" + t["id"], headers=headers).status_code == 404


def test_login_pkce_consumption_refresh_and_logout(client, student, headers, monkeypatch):
    gateway = {"x-gateway-secret": config["GATEWAY_SECRET"]}
    start = client.post("/internal/auth/start", headers=gateway).json()
    assert "code_challenge=" in start["url"] and "provider=google" in start["url"]
    auth.provider.next_tokens = {"access_token": student.token, "refresh_token": "fresh"}
    callback = client.post(
        "/internal/auth/callback", headers=gateway, json={"state": start["state"], "code": "test-code"}
    )
    assert callback.status_code == 200
    assert (
        client.post(
            "/internal/auth/callback", headers=gateway, json={"state": start["state"], "code": "test-code"}
        ).status_code
        == 401
    )
    h = {**gateway, "x-session": callback.json()["session"]}
    # Force an expiring access token, then exercise refresh under the row lock.
    with transaction() as db:
        entry = db.get(WebSession, auth.digest(h["x-session"]))
        entry.tokens = (
            auth.crypt()
            .encrypt(
                json.dumps(
                    {"access_token": issue(student.uid, student.sid, -1), "refresh_token": "old"}
                ).encode()
            )
            .decode()
        )
        db.commit()
    auth.provider.next_tokens = {"access_token": student.token, "refresh_token": "rotated"}
    assert client.get("/api/v1/me", headers=h).status_code == 200
    assert client.post("/internal/auth/logout", headers=h).status_code == 200
    assert client.get("/api/v1/me", headers=h).status_code == 401


def test_real_jwt_signature_issuer_audience_and_expiry(student, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        auth,
        "jwks",
        lambda: SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=KEY.public_key())),
    )
    provider = auth.SupabaseAuth()
    assert provider.claims(student.token)["sub"] == str(student.uid)
    assert pytest.raises(auth.ApiError, provider.claims, issue(student.uid, student.sid, -30))
    import jwt

    bad = jwt.encode(
        {
            "sub": str(student.uid),
            "session_id": str(student.sid),
            "iat": now(),
            "exp": now() + timedelta(hours=1),
            "aud": "wrong",
            "iss": "wrong",
        },
        KEY,
        algorithm="ES256",
    )
    assert pytest.raises(auth.ApiError, provider.claims, bad)


def test_creation_hook_rejects_other_accounts_and_providers():
    from sqlalchemy.exc import ProgrammingError

    with transaction() as runtime:
        assert (
            runtime.execute(text("select rolbypassrls from pg_roles where rolname=current_user")).scalar_one()
            is False
        )
        with pytest.raises(ProgrammingError):
            runtime.execute(text("select id from auth.users"))
        runtime.rollback()
    with create_engine(config["MIGRATION_DATABASE_URL"]).begin() as db:
        for email, provider, blocked in [
            ("student@somaiya.edu", "google", False),
            ("student@gmail.com", "google", True),
            ("student@somaiya.edu.attacker.test", "google", True),
            ("student@somaiya.edu", "email", True),
        ]:
            event = {"user": {"email": email, "app_metadata": {"provider": provider}}}
            value = db.execute(
                text("select duecare_internal.before_user_created(cast(:event as jsonb))"),
                {"event": json.dumps(event)},
            ).scalar_one()
            assert ("error" in value) is blocked


def test_partial_validation_date_only_edit_and_manual_provenance(client, headers):
    t = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Date-only task", "type": "assignment", "dueDate": "2026-10-20"},
    ).json()
    t = client.patch(
        "/api/v1/tasks/" + t["id"],
        headers=headers.fresh(),
        json={"revision": t["revision"], "notes": "Keep default cutoff"},
    ).json()
    assert t["dueAt"].startswith("2026-10-20T18:29")
    assert t["manualFieldOverrides"]["notes"]["recordedAt"]
    for invalid in [{"title": None}, {"estimatedEffortMinutes": -1}, {"status": "missed"}]:
        r = client.patch(
            "/api/v1/tasks/" + t["id"],
            headers=headers.fresh(),
            json={"revision": t["revision"], **invalid},
        )
        assert r.status_code == 422
    assert client.get("/api/v1/tasks?type=other", headers=headers).status_code == 422
    assert client.get("/api/v1/tasks?dateFrom=2026-10-01T00:00:00", headers=headers).status_code == 422
    assert client.get("/api/v1/tasks?cursor=not-base64", headers=headers).status_code == 422


def test_database_cross_owner_subject_fk(client, student):
    from sqlalchemy.exc import IntegrityError

    other = account()
    s = client.post(
        "/api/v1/subjects", headers=other.headers, json={"name": "Other subject", "kind": "theory"}
    ).json()
    with transaction(student.uid) as db:
        db.add(Task(user_id=student.uid, subject_id=s["id"], title="Bad link", type="assignment", data={}))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_concurrent_refresh_runs_once_under_database_lock(client, student, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from time import sleep

    calls = []
    with transaction() as db:
        entry = db.get(WebSession, auth.digest(student.handle))
        entry.tokens = (
            auth.crypt()
            .encrypt(
                json.dumps(
                    {"access_token": issue(student.uid, student.sid, -1), "refresh_token": "old"}
                ).encode()
            )
            .decode()
        )
        db.commit()

    def exchange(grant, payload):
        calls.append(grant)
        sleep(0.05)
        return {"access_token": student.token, "refresh_token": "new"}

    monkeypatch.setattr(auth.provider, "exchange", exchange)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.get("/api/v1/me", headers=student.headers), range(2)))
    assert [r.status_code for r in results] == [200, 200]
    assert calls == ["refresh_token"]


def test_signature_failure_and_missing_session_claim(student, monkeypatch):
    from types import SimpleNamespace

    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec

    monkeypatch.setattr(
        auth,
        "jwks",
        lambda: SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(
                key=ec.generate_private_key(ec.SECP256R1()).public_key()
            )
        ),
    )
    with pytest.raises(auth.ApiError):
        auth.SupabaseAuth().claims(student.token)
    monkeypatch.setattr(
        auth,
        "jwks",
        lambda: SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=KEY.public_key())),
    )
    payload = jwt.decode(student.token, options={"verify_signature": False})
    payload.pop("session_id")
    with pytest.raises(auth.ApiError):
        auth.SupabaseAuth().claims(jwt.encode(payload, KEY, algorithm="ES256"))
