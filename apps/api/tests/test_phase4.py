"""Real restricted Postgres, synthetic Auth/Google: privacy, activity and recovery acceptance."""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select, text

from duecare import google, interpret, privacy
from duecare.common import work
from duecare.db import transaction
from duecare.errors import ApiError
from duecare.models import (
    Connection,
    History,
    OAuthGrant,
    ReviewItem,
    SourceEvent,
    SourceRecord,
    Task,
    TaskEvidence,
    now,
)
from tests.conftest import account, config
from tests.fake_google import FakeGoogle
from tests.test_phase2 import connect, fresh


@pytest.fixture
def source(client, headers, monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(google, "provider", fake)
    cid = connect(client, headers, fake)
    return cid, fake


def imported(uid, cid, key="activity:1", manual=False):
    with work({"id": str(uid)}) as db:
        t = Task(
            user_id=uid,
            title="Synthetic work",
            type="assignment",
            data={
                "sources": ["gmail"],
                "manualFieldOverrides": {"notes": True} if manual else {},
                "notes": "My note" if manual else "",
            },
        )
        r = SourceRecord(
            user_id=uid,
            connection_id=cid,
            provider_id="record:" + key,
            kind="gmail_message",
            processing_state="interpreted",
            processing_version="fixture",
            data={},
            title="Synthetic notice",
        )
        db.add_all([t, r])
        db.flush()
        e = SourceEvent(
            user_id=uid,
            source_record_id=r.id,
            event_key="fixture",
            event_type="new_work",
            identity_key=key,
            outcome="created",
            task_id=t.id,
            processing_version="fixture",
            data={"links": ["https://example.test/private"]},
        )
        db.add(e)
        db.flush()
        db.add(TaskEvidence(user_id=uid, task_id=t.id, event_id=e.id, method="fixture", state="active"))
        interpret.history(db, t, "imported", {"title": t.title}, e)
        return str(t.id), str(r.id), str(e.id)


def deletion(client, headers, cid):
    c = next(
        c for c in client.get("/api/v1/connections", headers=headers).json()["items"] if c["id"] == str(cid)
    )
    r = client.post(
        "/api/v1/privacy/source-data-deletions",
        headers=fresh(headers),
        json={"connectionId": str(cid), "revision": c["revision"]},
    )
    assert r.status_code == 200, r.text
    return r.json()


def finish_deletion(client, headers, job):
    for _ in range(100):
        r = client.post("/api/v1/privacy/jobs/" + job["id"] + "/advance", headers=fresh(headers))
        assert r.status_code == 200, r.text
        job = r.json()
        if job["status"] == "completed":
            return job
    pytest.fail("Deletion did not terminate")


def test_activity_read_paging_and_owner_isolation(client, headers, student, source):
    cid, _ = source
    tid, _, _ = imported(student.uid, cid)
    out = client.get("/api/v1/activity?read=false&limit=1", headers=headers).json()
    item = out["items"][0]
    assert item["targetId"] == tid and out["unreadCount"] == 1
    other = account()
    assert (
        client.patch(
            "/api/v1/activity/" + item["id"],
            headers=other.headers,
            json={"read": True, "revision": item["revision"]},
        ).status_code
        == 404
    )
    marked = client.patch(
        "/api/v1/activity/" + item["id"], headers=headers, json={"read": True, "revision": item["revision"]}
    ).json()
    assert marked["readAt"]
    assert client.get("/api/v1/activity?read=false", headers=headers).json()["items"] == []
    client.patch(
        "/api/v1/activity/" + item["id"],
        headers=headers,
        json={"read": False, "revision": marked["revision"]},
    )
    assert client.get("/api/v1/activity", headers=headers).json()["unreadCount"] == 1
    # Marking everything read leaves other students' activity untouched.
    assert client.post("/api/v1/activity/read-all", headers=fresh(other.headers)).json() == {"updated": 0}
    assert client.post("/api/v1/activity/read-all", headers=fresh(headers)).json() == {"updated": 1}
    assert client.get("/api/v1/activity", headers=headers).json()["unreadCount"] == 0


def test_source_deletion_preserves_student_work_and_other_source(client, headers, student, source):
    cid, fake = source
    gone, _, _ = imported(student.uid, cid, "delete")
    edited, _, _ = imported(student.uid, cid, "keep-edit", manual=True)
    supported, rid, eid = imported(student.uid, cid, "keep-other")
    fake.identity_claims["sub"] = "other-google-account"
    othercid = connect(client, headers, fake, "classroom", code="other")
    with work({"id": str(student.uid)}) as db:
        r = SourceRecord(
            user_id=student.uid,
            connection_id=othercid,
            provider_id="other-record",
            kind="classroom_coursework",
            processing_state="interpreted",
            processing_version="fixture",
            data={},
        )
        db.add(r)
        db.flush()
        e = SourceEvent(
            user_id=student.uid,
            source_record_id=r.id,
            event_key="other",
            event_type="new_work",
            identity_key="other-identity",
            outcome="linked",
            task_id=supported,
            processing_version="fixture",
            data={},
        )
        db.add(e)
        db.flush()
        db.add(
            TaskEvidence(
                user_id=student.uid, task_id=supported, event_id=e.id, method="fixture", state="active"
            )
        )
    manual = client.post(
        "/api/v1/tasks", headers=fresh(headers), json={"title": "Student-created", "type": "assignment"}
    ).json()
    job = deletion(client, headers, cid)
    assert client.post(f"/api/v1/connections/{cid}/sync", headers=fresh(headers), json={}).status_code == 409
    result = finish_deletion(client, headers, job)
    assert result["progress"]["deletedTasks"] == 1 and result["progress"]["preservedTasks"] == 2
    assert client.get("/api/v1/tasks/" + gone, headers=headers).status_code == 404
    t = client.get("/api/v1/tasks/" + edited, headers=headers).json()
    assert t["sources"] == ["manual"] and t["notes"] == "My note"
    assert client.get("/api/v1/tasks/" + supported, headers=headers).json()["sources"] == ["classroom"]
    assert client.get("/api/v1/tasks/" + manual["id"], headers=headers).status_code == 200
    with transaction(student.uid) as db:
        assert not db.scalar(select(SourceRecord.id).where(SourceRecord.connection_id == cid))
        assert db.scalar(
            select(OAuthGrant.id).where(OAuthGrant.status == "active")
        )  # deletion is separate from disconnect
        assert not db.scalar(select(History.id).where(History.changes["_eventId"].astext == eid))
        assert db.get(Connection, __import__("uuid").UUID(cid)).checkpoint == {}
    assert (
        client.post("/api/v1/privacy/jobs/" + job["id"] + "/advance", headers=fresh(headers)).json() == result
    )


def test_deleted_task_cannot_reappear_and_restore_is_explicit(client, headers, student, source):
    cid, _ = source
    tid, rid, _ = imported(student.uid, cid, "lms:activity:1")
    t = client.get("/api/v1/tasks/" + tid, headers=headers).json()
    assert (
        client.delete(
            "/api/v1/tasks/" + tid + "?revision=" + str(t["revision"]), headers=fresh(headers)
        ).status_code
        == 200
    )
    with work({"id": str(student.uid)}) as db:
        conn = db.get(Connection, __import__("uuid").UUID(cid))
        record = db.get(SourceRecord, __import__("uuid").UUID(rid))
        cand = interpret.Cand(intent="new_work", identity_key="lms:activity:1", title="Would recreate")
        assert interpret.apply_candidate(db, str(student.uid), {}, record, 0, cand, 55) == "ignored_deleted"
        # Suppression is per activity, not per message or account.
        assert not privacy.suppressed(db, conn, "lms:activity:2")
    rows = client.get("/api/v1/suppression-records", headers=headers).json()["items"]
    assert len(rows) == 1 and set(rows[0]) == {"id", "createdAt", "restoredAt", "revision"}
    other = account()
    assert (
        client.post(
            "/api/v1/suppression-records/" + rows[0]["id"] + "/restore", headers=other.headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/suppression-records/" + rows[0]["id"] + "/restore", headers=fresh(headers)
        ).status_code
        == 200
    )
    assert (
        client.get("/api/v1/tasks/" + tid, headers=headers).status_code == 404
    )  # restore is not a backup restore
    assert client.post("/api/v1/connections/" + cid + "/reimport", headers=fresh(headers)).status_code == 200
    with transaction(student.uid) as db:
        assert not privacy.suppressed(db, db.get(Connection, __import__("uuid").UUID(cid)), "lms:activity:1")
        assert (
            db.get(SourceRecord, __import__("uuid").UUID(rid)).processing_state == "awaiting_interpretation"
        )


def test_disconnect_retry_is_durable_and_shared_grant_safe(client, headers, student, source, monkeypatch):
    cid, fake = source
    _, rid, _ = imported(student.uid, cid)

    def down(token):
        raise google.SourceError("retryable", "Synthetic outage")

    monkeypatch.setattr(fake, "revoke", down)
    c = client.get("/api/v1/connections", headers=headers).json()["items"][0]
    result = client.delete(
        f"/api/v1/connections/{cid}?revision={c['revision']}", headers=fresh(headers)
    ).json()
    assert result["privacyJob"]["status"] == "waiting_retry"
    from duecare.sources_api import link_account

    with work({"id": str(student.uid)}) as db:
        with pytest.raises(ApiError, match="Finish the source privacy operation before reconnecting"):
            link_account(db, student.uid, "google-sub-1", "student@somaiya.edu", {}, {}, ["gmail"])
    assert client.get("/api/v1/connections", headers=headers).json()["items"][0]["status"] == "disconnected"
    assert client.post(f"/api/v1/connections/{cid}/sync", headers=fresh(headers), json={}).status_code == 409
    monkeypatch.setattr(fake, "revoke", lambda token: None)
    result = finish_deletion(client, headers, result["privacyJob"])
    assert result["status"] == "completed"
    with transaction(student.uid) as db:
        assert db.get(SourceRecord, __import__("uuid").UUID(rid))


def test_expiry_cleanup_is_bounded_and_preserves_linked_evidence(client, headers, student, source):
    cid, _ = source
    _, rid, _ = imported(student.uid, cid)
    with transaction(student.uid) as db:
        r = db.get(SourceRecord, __import__("uuid").UUID(rid))
        r.expires_at = now() - timedelta(days=1)
        for i in range(105):
            db.add(
                SourceRecord(
                    user_id=student.uid,
                    connection_id=cid,
                    provider_id="expired:" + str(i),
                    kind="gmail_message",
                    processing_state="ignored",
                    processing_version="fixture",
                    data={},
                    expires_at=now() - timedelta(days=1),
                )
            )
        db.commit()
    client.get("/api/v1/activity", headers=headers)
    with transaction(student.uid) as db:
        assert len(list(db.scalars(select(SourceRecord)))) == 6
        assert db.get(SourceRecord, __import__("uuid").UUID(rid))
    client.get("/api/v1/activity", headers=headers)
    with transaction(student.uid) as db:
        assert len(list(db.scalars(select(SourceRecord)))) == 1


def test_account_deletion_freezes_all_tabs_and_resumes_after_auth_removal(
    client, headers, student, source, monkeypatch
):
    cid, fake = source
    imported(student.uid, cid)
    other = account()
    client.post(
        "/api/v1/tasks", headers=other.headers, json={"title": "Keep other student", "type": "assignment"}
    )
    assert (
        client.post(
            "/api/v1/privacy/account-deletion", headers=headers, json={"confirmation": "no"}
        ).status_code
        == 422
    )
    start = client.post(
        "/api/v1/privacy/account-deletion", headers=headers, json={"confirmation": "DELETE"}
    ).json()
    token = start["resumeToken"]
    assert client.get("/api/v1/privacy/account-deletion", headers=headers).json() == start
    assert (
        client.post(
            "/api/v1/privacy/account-deletion", headers=headers, json={"confirmation": "DELETE"}
        ).json()
        == start
    )
    assert client.get("/api/v1/tasks", headers=headers).status_code == 409
    gateway = {"x-gateway-secret": headers["x-gateway-secret"]}
    assert (
        client.post(
            "/internal/privacy/account-deletion", headers=gateway, json={"token": "a" * 64, "advance": True}
        ).status_code
        == 404
    )

    def down(token):
        raise google.SourceError("retryable", "Synthetic outage")

    monkeypatch.setattr(fake, "revoke", down)
    r = client.post(
        "/internal/privacy/account-deletion", headers=gateway, json={"token": token, "advance": True}
    )
    assert r.json()["status"] == "waiting_retry"
    monkeypatch.setattr(fake, "revoke", lambda token: None)
    for _ in range(80):
        r = client.post(
            "/internal/privacy/account-deletion", headers=gateway, json={"token": token, "advance": True}
        )
        assert r.status_code == 200, r.text
        if r.json()["status"] == "completed":
            break
    assert r.json()["status"] == "completed"
    assert client.get("/api/v1/me", headers=headers).status_code == 401
    assert (
        client.post(
            "/internal/privacy/account-deletion", headers=gateway, json={"token": token, "advance": True}
        ).json()
        == r.json()
    )
    with create_engine(config["MIGRATION_DATABASE_URL"]).connect() as db:
        assert not db.scalar(text("select id from auth.users where id=:id"), {"id": student.uid})
        assert db.scalar(text("select id from auth.users where id=:id"), {"id": other.uid})
        assert not db.scalar(text("select user_id from duecare.tasks where user_id=:id"), {"id": student.uid})
        receipt = db.execute(
            text("select user_id,status from duecare_internal.account_deletions where id=:id"),
            {"id": start["id"]},
        ).one()
        assert receipt == (None, "completed")
    assert (
        client.get("/api/v1/tasks", headers=other.headers).json()["items"][0]["title"] == "Keep other student"
    )


def test_source_deletion_scrubs_cached_results(client, headers, student, source):
    cid, _ = source
    key = fresh(headers)
    old = client.post("/api/v1/tasks", headers=key, json={"title": "Keep student work", "type": "assignment"})
    assert old.status_code == 201
    task = old.json()
    path = "/api/v1/tasks/" + task["id"]
    payload = {"revision": task["revision"], "notes": "Student note"}
    assert client.patch(path, headers=key, json=payload).status_code == 200
    finish_deletion(client, headers, deletion(client, headers, cid))
    replay = client.patch(path, headers=key, json=payload)
    assert replay.status_code == 410


def test_new_tables_and_self_delete_function_are_private(student):
    with create_engine(config["MIGRATION_DATABASE_URL"]).connect() as db:
        for name in ("activity_notifications", "suppression_records", "privacy_jobs"):
            assert db.execute(
                text(
                    "select relrowsecurity,relforcerowsecurity from pg_class where oid=cast(:name as regclass)"
                ),
                {"name": "duecare." + name},
            ).one() == (True, True)
        assert (
            db.scalar(
                text(
                    "select has_function_privilege('anon','duecare_internal.delete_own_auth_account(uuid)','execute')"
                )
            )
            is False
        )
        assert (
            db.scalar(
                text(
                    "select has_function_privilege('authenticated','duecare_internal.delete_own_auth_account(uuid)','execute')"
                )
            )
            is False
        )
    with transaction(student.uid) as db:
        with pytest.raises(Exception, match="Self-deletion checkpoint required"):
            db.execute(text("select duecare_internal.delete_own_auth_account(:id)"), {"id": str(student.uid)})


def test_restore_waits_for_pending_deletion_and_task_evidence_is_chunked(client, headers, student, source):
    cid, _ = source
    tid, rid, _ = imported(student.uid, cid)
    with work({"id": str(student.uid)}) as db:
        for i in range(28):
            e = SourceEvent(
                user_id=student.uid,
                source_record_id=rid,
                event_key="chunk:" + str(i),
                event_type="new_work",
                identity_key="chunk:" + str(i),
                outcome="linked",
                task_id=tid,
                processing_version="fixture",
                data={},
            )
            db.add(e)
            db.flush()
            db.add(TaskEvidence(user_id=student.uid, task_id=tid, event_id=e.id, method="fixture"))
    job = deletion(client, headers, cid)
    step = client.post("/api/v1/privacy/jobs/" + job["id"] + "/advance", headers=fresh(headers)).json()
    assert step["status"] == "pending" and not step["progress"].get("deletedTasks")
    with transaction(student.uid) as db:
        assert len(list(db.scalars(select(TaskEvidence).where(TaskEvidence.task_id == tid)))) == 4
    rows = client.get("/api/v1/suppression-records", headers=headers).json()["items"]
    result = client.post("/api/v1/suppression-records/" + rows[0]["id"] + "/restore", headers=fresh(headers))
    assert result.status_code == 409 and result.json()["code"] == "PRIVACY_IN_PROGRESS"
    done = finish_deletion(client, headers, job)
    assert done["progress"]["deletedTasks"] == 1


def test_expired_review_cannot_be_opened_or_resolved(client, headers, student, source):
    cid, _ = source
    tid, rid, eid = imported(student.uid, cid)
    with work({"id": str(student.uid)}) as db:
        db.get(SourceRecord, __import__("uuid").UUID(rid)).expires_at = now() - timedelta(days=1)
        item = ReviewItem(
            user_id=student.uid,
            task_id=tid,
            source_record_id=rid,
            event_id=eid,
            issue_type="conflict",
            question="Synthetic expired question",
            data={},
        )
        db.add(item)
        db.flush()
        review_id = str(item.id)
    assert client.get("/api/v1/review-items/" + review_id, headers=headers).status_code == 410
    assert (
        client.post(
            "/api/v1/review-items/" + review_id + "/resolve",
            headers=fresh(headers),
            json={"revision": 1, "action": "keep_current"},
        ).status_code
        == 410
    )
    assert client.get("/api/v1/review-items", headers=headers).json()["items"] == []


def test_default_server_logs_do_not_expose_private_exception_parameters():
    import logging
    import sys

    from duecare.safe_logs import SafeException

    try:
        raise RuntimeError("synthetic private token and source excerpt")
    except RuntimeError:
        record = logging.LogRecord(
            "uvicorn.error", logging.ERROR, "fixture", 1, "raw error", (), sys.exc_info()
        )
    assert SafeException().filter(record)
    formatted = logging.Formatter().format(record)
    assert formatted == "ASGI application error type=RuntimeError"
    assert logging.getLogger("uvicorn.access").disabled
