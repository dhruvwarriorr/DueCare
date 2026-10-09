import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlparse

import pytest
from sqlalchemy import create_engine, func, select, text

from duecare import auth, google, mail, sync
from duecare.config import settings
from duecare.db import transaction
from duecare.models import (
    Connection,
    OAuthGrant,
    SourceAttachment,
    SourceRecord,
    Subject,
    SyncJob,
    Task,
    now,
)
from tests.conftest import account, config
from tests.fake_google import FakeGoogle, eml

REFERENCE = Path(__file__).resolve().parents[3] / "docs/reference-files/emails"


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    provider = FakeGoogle()
    monkeypatch.setattr(google, "provider", provider)
    return provider


def fresh(headers):
    return headers.fresh() if hasattr(headers, "fresh") else headers


def connect(
    client, headers, fake, service="gmail", sub="google-sub-1", email="student@somaiya.edu", code="c1"
):
    fake.service = service
    fake.identity_claims = {"sub": sub, "email": email, "email_verified": True, "name": "Source Account"}
    r = client.post("/api/v1/connections/authorize", headers=headers, json={"service": service})
    assert r.status_code == 200, r.text
    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
    r = client.get(f"/api/v1/connections/oauth/callback?state={state}&code={code}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["connectionId"]


def run(client, headers, conn_id, trigger="manual", limit=50):
    r = client.post(f"/api/v1/connections/{conn_id}/sync", headers=fresh(headers), json={"trigger": trigger})
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    for _ in range(limit):
        if job["status"] in ("completed", "failed", "cancelled", "waiting_retry"):
            return job
        r = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers)
        assert r.status_code == 200, r.text
        job = r.json()
    raise AssertionError("sync did not finish")


def records(uid, **filters):
    with transaction(uid) as db:
        stmt = select(SourceRecord).where(SourceRecord.user_id == uid)
        for key, value in filters.items():
            stmt = stmt.where(getattr(SourceRecord, key) == value)
        return list(db.scalars(stmt.order_by(SourceRecord.created_at)))


def test_mime_decoding_sections_tables_links_and_identity():
    html = (
        "<p>Room update for IA1. Login by 13:30.</p>"
        "<table><tr><th>Batch</th><th>Room</th></tr><tr><td><p>B1</p></td><td>B116A</td></tr>"
        "<tr><td>B2</td><td>B115A</td></tr></table>"
        '<p><a href="https://lms.example.test/mod/assign/view.php?id=42">Activity</a></p>'
        "<script>alert(1)</script>"
        "<blockquote><p>On Mon, Teacher wrote:</p><p>Quiz starts 13:40</p></blockquote>"
    )
    raw = eml(
        '"Prof. Example (via LMS)" <Faculty.Example@Somaiya.edu>',
        "=?utf-8?q?IA1_=E2=80=93_room_update?=",
        "plain fallback",
        "<abc@lms.example.test>",
        html=html,
        attachment=("seating.pdf", b"%PDF-1.4 bytes"),
    )
    d = mail.decode(raw)
    assert d.sender_email == "faculty.example@somaiya.edu" and d.sender_name.startswith("Prof. Example")
    assert d.subject == "IA1 – room update"
    authored = d.authored_text
    assert "B2 | B115A" in authored and "B1 | B116A" in authored and "alert" not in authored
    quoted = [s for s in d.sections if s.kind == "quoted"]
    assert quoted and "Quiz starts 13:40" in quoted[0].text
    assert d.attachments == [
        {
            "kind": "file",
            "title": "seating.pdf",
            "reference": "mime-part:4",
            "mediaType": "application/pdf",
            "sizeBytes": 14,
        }
    ]
    assert [link["reference"] for link in d.links] == ["https://lms.example.test/mod/assign/view.php?id=42"]
    # Transport headers and export filenames do not change content identity.
    other = eml(
        '"Prof. Example (via LMS)" <Faculty.Example@Somaiya.edu>',
        "=?utf-8?q?IA1_=E2=80=93_room_update?=",
        "plain fallback",
        "<abc@lms.example.test>",
        sent=d.sent_at,
        html=html,
        attachment=("seating.pdf", b"%PDF-1.4 bytes"),
        received="from another.hop by mx.google.com",
    )
    assert mail.decode(other).content_hash() == d.content_hash()

    plain = mail.decode(
        eml(
            "teacher@somaiya.edu",
            "Re: Viva",
            "Viva moved to Friday.\n\nOn Tue, 1 Sep 2026, Teacher wrote:\n> Viva on Thursday\n\n-- \nTeacher\n"
            "To unsubscribe from this list click here",
            "<v@x>",
        )
    )
    assert [s.kind for s in plain.sections] == ["authored", "quoted", "signature", "footer"]
    assert plain.sections[1].attribution.startswith("On Tue")


@pytest.mark.skipif(not REFERENCE.exists(), reason="reference archive not present")
def test_reference_exports_decode_and_deduplicate_by_content_not_filename():
    decoded = {f.name: mail.decode(f.read_bytes()) for f in REFERENCE.glob("*.eml")}
    assert len(decoded) == 22
    for name, d in decoded.items():
        assert d.sender_email == "lms-kjsse@somaiya.edu" and d.sent_at and d.sections
        if name.endswith(" copy.eml"):
            assert decoded[name.replace(" copy.eml", ".eml")].content_hash() == d.content_hash()
    a = decoded["Assignment submission confirmation - EXP6-BST.eml"]
    b = decoded["Assignment submission confirmation - EXP6-BST(1).eml"]
    assert a.message_id != b.message_id and a.content_hash() != b.content_hash()
    assert a.authentication["authservId"] == "mx.google.com"


def test_connection_requires_session_and_own_state_and_encrypts_tokens(client, headers, student, fake):
    assert client.post("/api/v1/connections/authorize", json={"service": "gmail"}).status_code == 401
    r = client.post("/api/v1/connections/authorize", headers=headers, json={"service": "gmail"})
    q = parse_qs(urlparse(r.json()["url"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["access_type"] == ["offline"]
    assert q["include_granted_scopes"] == ["true"] and q["redirect_uri"] == [
        "http://localhost:3001/connections/callback"
    ]
    assert q["scope"][0].split() == [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]
    state = q["state"][0]
    other = account()
    fake.service = "gmail"
    # Another student's session cannot complete this student's authorization.
    assert (
        client.get(
            f"/api/v1/connections/oauth/callback?state={state}&code=x", headers=other.headers
        ).status_code
        == 400
    )
    r = client.post("/api/v1/connections/authorize", headers=headers, json={"service": "gmail"})
    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
    fake.identity_claims = {"sub": "personal-sub", "email": "Someone@Gmail.com", "email_verified": True}
    ok = client.get(f"/api/v1/connections/oauth/callback?state={state}&code=personal", headers=headers)
    assert ok.status_code == 200 and ok.json()["accountEmail"] == "someone@gmail.com"
    assert (
        client.get(
            f"/api/v1/connections/oauth/callback?state={state}&code=personal", headers=headers
        ).status_code
        == 400
    )
    listed = client.get("/api/v1/connections", headers=headers).json()["items"]
    assert [c["service"] for c in listed] == ["gmail"] and listed[0]["account"][
        "email"
    ] == "someone@gmail.com"
    assert "refresh" not in json.dumps(listed) and "access-" not in json.dumps(listed)
    with create_engine(config["MIGRATION_DATABASE_URL"]).begin() as db:
        grant = db.execute(
            text("select refresh_token,access_token,key_version from duecare.oauth_grants where user_id=:u"),
            {"u": student.uid},
        ).all()
        assert len(grant) == 1
        assert all("refresh-" not in g.refresh_token and "access-" not in g.access_token for g in grant)
        assert {g.key_version for g in grant} == {"v2"}
        # A personal source account never becomes a login identity.
        assert (
            db.execute(
                text("select count(*) from auth.identities where user_id=:u"), {"u": student.uid}
            ).scalar()
            == 1
        )
    assert client.get("/api/v1/connections", headers=other.headers).json()["items"] == []


def test_shared_grant_refresh_token_preserved_and_service_specific_disconnect(client, headers, student, fake):
    gmail = connect(client, headers, fake, "gmail", code="first")
    fake.omit_refresh = True
    classroom = connect(client, headers, fake, "classroom", code="second")
    with transaction(student.uid) as db:
        grant = db.scalar(select(OAuthGrant))
        assert google.vault().decrypt(grant.refresh_token, grant.key_version) == "refresh-first"
        assert {*google.SERVICE_SCOPES["gmail"], *google.SERVICE_SCOPES["classroom"]} <= set(grant.scopes)
    conns = {c["service"]: c for c in client.get("/api/v1/connections", headers=headers).json()["items"]}
    r = client.delete(
        f"/api/v1/connections/{gmail}?revision={conns['gmail']['revision']}", headers=fresh(headers)
    )
    assert r.json()["googleAccessRevoked"] is False and fake.revoked == []
    r = client.delete(
        f"/api/v1/connections/{classroom}?revision={conns['classroom']['revision']}", headers=fresh(headers)
    )
    assert r.json()["googleAccessRevoked"] is True and fake.revoked == ["refresh-first"]
    with transaction(student.uid) as db:
        grant = db.scalar(select(OAuthGrant))
        assert grant.refresh_token is None and grant.status == "revoked"
    assert (
        client.post(f"/api/v1/connections/{gmail}/sync", headers=fresh(headers), json={}).status_code == 409
    )


def test_missing_permission_is_rejected_and_unused_grant_revoked(client, headers, fake):
    fake.service, fake.scopes = "classroom", ["openid", "email", google.SERVICE_SCOPES["classroom"][0]]
    r = client.post("/api/v1/connections/authorize", headers=headers, json={"service": "classroom"})
    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
    r = client.get(f"/api/v1/connections/oauth/callback?state={state}&code=partial", headers=headers)
    assert r.status_code == 403 and r.json()["code"] == "PERMISSION_NOT_GRANTED"
    assert fake.revoked == ["refresh-partial"]
    assert client.get("/api/v1/connections", headers=headers).json()["items"] == []


def gmail_fixture(fake):
    t0 = now() - timedelta(days=3)
    fake.add_message("m1", eml("lms-kjsse@somaiya.edu", "EXP6-BST is due", "Due 21 Sept", "<m1@lms>"), ts=t0)
    fake.add_message(
        "m2", eml("friend@gmail.com", "Weekend plans", "Personal text", "<m2@x>"), ts=t0 + timedelta(hours=1)
    )
    fake.add_message(
        "m3",
        eml("spam.teacher@somaiya.edu", "Blocked notice", "Secret body", "<m3@x>"),
        ts=t0 + timedelta(hours=2),
    )
    fake.add_message(
        "m4",
        eml("coach@club.example", "Included sender", "Quiz on Friday", "<m4@x>"),
        ts=t0 + timedelta(hours=3),
    )
    fake.add_message(
        "m5",
        eml("lms-kjsse@somaiya.edu", "EXP6-BST is due", "Due 21 Sept", "<m1@lms>", sent=None),
        ts=t0 + timedelta(hours=4),
    )
    fake.add_message(
        "m6", eml("me@somaiya.edu", "Draft", "draft", "<m6@x>"), labels=["DRAFT"], ts=t0 + timedelta(hours=5)
    )
    fake.add_message(
        "old", eml("lms-kjsse@somaiya.edu", "Old", "Old", "<old@x>"), ts=now() - timedelta(days=120)
    )


def test_gmail_initial_import_pagination_sender_rules_and_no_tasks(client, headers, student, fake):
    gmail_fixture(fake)
    # Make the duplicate a byte-identical copy so the Message-ID and decoded content match.
    fake.messages["m5"]["raw"] = fake.messages["m1"]["raw"]
    put = lambda e, a: client.put(  # noqa: E731
        "/api/v1/sender-preferences/" + quote(e), headers=headers, json={"action": a}
    )
    assert put(" Spam.Teacher@SOMAIYA.edu ", "block").status_code == 200
    assert put("coach@club.example", "include").status_code == 200
    conn = connect(client, headers, fake)
    job = run(client, headers, conn)
    assert job["status"] == "completed", job
    assert job["progress"]["pages"] >= 3 and job["progress"]["listed"] == 6
    by_id = {r.provider_id.rsplit(":", 1)[1]: r for r in records(student.uid)}
    assert set(by_id) == {"m1", "m2", "m3", "m4", "m5"}
    original, copy = sorted((by_id["m1"], by_id["m5"]), key=lambda r: r.processing_state)
    assert original.processing_state == "awaiting_interpretation" and original.title == "EXP6-BST is due"
    assert copy.processing_state == "duplicate" and copy.data["duplicateOf"] == str(original.id)
    assert (
        by_id["m4"].processing_state == "awaiting_interpretation" and by_id["m4"].reason == "sender_included"
    )
    for gid, state in (("m2", "ignored"), ("m3", "blocked")):
        r = by_id[gid]
        assert r.processing_state == state and r.title is None and r.data == {} and r.expires_at
    # Blocked and non-academic mail bodies are never fetched.
    assert "gmail_raw:m3" not in fake.calls and "gmail_raw:m2" not in fake.calls
    assert by_id["m1"].provider_id == "gmail:google-sub-1:m1"
    with transaction(student.uid) as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 0
        assert db.get(Connection, conn).checkpoint["historyId"] == "107"
        assert "Due 21 Sept" not in json.dumps(original.data)
    summary = client.get("/api/v1/connections", headers=headers).json()["items"][0]["records"]
    assert {k: summary[k] for k in ("duplicates", "blocked")} == {"duplicates": 1, "blocked": 1}
    assert summary["awaitingInterpretation"] + summary["ignored"] + summary["interpreted"] == 3
    overview = client.get("/api/v1/overview", headers=headers).json()
    assert overview["sync"][0]["lastJob"]["status"] == "completed" and overview["counts"]["due"] == 0


def test_incremental_history_and_expired_history_fallback(client, headers, student, fake):
    gmail_fixture(fake)
    conn = connect(client, headers, fake)
    run(client, headers, conn)
    before = len(records(student.uid))
    fake.add_message("m7", eml("teacher@somaiya.edu", "New quiz", "Quiz", "<m7@x>"))
    fake.calls.clear()
    job = run(client, headers, conn)
    assert job["status"] == "completed" and "gmail_list" in fake.calls and "gmail_history" in fake.calls
    assert fake.calls.index("gmail_list") < fake.calls.index("gmail_history")
    assert len(records(student.uid)) == before + 1 and job["progress"]["stored"] == 1
    fake.history_expired = True
    job = run(client, headers, conn)
    assert job["status"] == "completed" and job["progress"]["historyResets"] == 1
    assert len(records(student.uid)) == before + 1  # Fallback relisting creates no duplicates.


def test_interrupted_job_resumes_from_checkpoint_and_lease_blocks_other_tabs(
    client, headers, student, fake, monkeypatch
):
    gmail_fixture(fake)
    conn = connect(client, headers, fake)
    # Expire the advance just after its first listing, independently of how often
    # the concurrent interpretation lane checks the time.
    clock = [time.monotonic()]
    monkeypatch.setattr(sync, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    listing = fake.gmail_list

    def slow_listing(*args, **kwargs):
        page = listing(*args, **kwargs)
        clock[0] += 4
        return page

    monkeypatch.setattr(fake, "gmail_list", slow_listing)
    monkeypatch.setattr(settings(), "sync_work_budget_seconds", 3)
    job = client.post(
        f"/api/v1/connections/{conn}/sync", headers=fresh(headers), json={"trigger": "open"}
    ).json()["job"]
    job = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers).json()
    assert job["status"] == "queued" and not job["leased"]
    partial = len(records(student.uid))
    assert job["progress"].get("pages") == 1
    # Another tab asking to sync gets the same single active job.
    again = client.post(
        f"/api/v1/connections/{conn}/sync", headers=fresh(headers), json={"trigger": "open"}
    ).json()
    assert again["job"]["id"] == job["id"] and again["created"] is False
    with transaction(student.uid) as db:
        row = db.get(SyncJob, job["id"])
        row.lease_owner, row.lease_expires_at = "other-tab", now() + timedelta(minutes=1)
        db.commit()
    blocked = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers)
    assert blocked.status_code == 409 and blocked.json()["code"] == "SYNC_IN_PROGRESS"
    with transaction(student.uid) as db:
        db.get(SyncJob, job["id"]).lease_expires_at = now() - timedelta(
            seconds=1
        )  # Closed tab's lease expired.
        db.commit()
    monkeypatch.setattr(settings(), "sync_work_budget_seconds", 1000)
    job = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers).json()
    assert job["status"] == "completed" and len(records(student.uid)) == 5 >= partial
    assert len({r.provider_id for r in records(student.uid)}) == 5


def test_concurrent_advances_process_once(client, headers, student, fake):
    gmail_fixture(fake)
    conn = connect(client, headers, fake)
    job = client.post(f"/api/v1/connections/{conn}/sync", headers=fresh(headers), json={}).json()["job"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers), range(2)
            )
        )
    assert sorted(r.status_code for r in results) in ([200, 200], [200, 409])
    run(client, headers, conn)
    assert len(records(student.uid)) == 5
    assert sum(1 for c in fake.calls if c == "gmail_raw:m1") == 1


def test_temporary_failure_backs_off_preserves_partial_results_and_resumes(client, headers, student, fake):
    gmail_fixture(fake)
    conn = connect(client, headers, fake)
    fake.fail("gmail_metadata", times=1)
    job = run(client, headers, conn)
    assert job["status"] == "waiting_retry" and job["attempts"] == 1 and job["nextRetryAt"]
    assert job["error"]["code"] == "PROVIDER_TEMPORARY"
    calls = len(fake.calls)
    waiting = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers).json()
    assert waiting["status"] == "waiting_retry" and len(fake.calls) == calls
    with transaction(student.uid) as db:
        db.get(SyncJob, job["id"]).next_retry_at = now() - timedelta(seconds=1)
        db.commit()
    job = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers).json()
    assert job["status"] == "completed" and job["attempts"] == 0 and len(records(student.uid)) == 5


def test_block_applied_while_fetch_in_flight_cannot_commit_content(client, headers, student, fake):
    fake.add_message("m1", eml("faculty@somaiya.edu", "IA notice", "Private notice body", "<n1@x>"))
    conn = connect(client, headers, fake)

    def block_now(gid):
        assert (
            client.put(
                "/api/v1/sender-preferences/faculty%40somaiya.edu", headers=headers, json={"action": "block"}
            ).status_code
            == 200
        )

    fake.on_raw = block_now
    job = run(client, headers, conn)
    assert job["status"] == "completed"
    (record,) = records(student.uid)
    assert record.processing_state == "blocked" and record.title is None and record.data == {}


def test_block_suppresses_unprocessed_records_preserves_tasks_and_reprocess_restores(
    client, headers, student, fake
):
    fake.add_message(
        "m1",
        eml(
            "faculty@somaiya.edu",
            "IA notice",
            "See https://lms.example.test/mod/assign/view.php?id=7",
            "<n1@x>",
            attachment=("brief.pdf", b"%PDF"),
        ),
    )
    conn = connect(client, headers, fake)
    run(client, headers, conn)
    task = client.post(
        "/api/v1/tasks", headers=headers, json={"title": "Kept task", "type": "assignment"}
    ).json()
    (record,) = records(student.uid)
    with transaction(student.uid) as db:
        assert db.scalar(select(func.count()).select_from(SourceAttachment)) == 2
    r = client.put(
        "/api/v1/sender-preferences/FACULTY%40somaiya.edu", headers=headers, json={"action": "block"}
    )
    assert r.json()["suppressedRecords"] == 1 and r.json()["email"] == "faculty@somaiya.edu"
    (record,) = records(student.uid)
    assert record.processing_state == "blocked" and record.title is None
    with transaction(student.uid) as db:
        assert db.scalar(select(func.count()).select_from(SourceAttachment)) == 0
    assert client.get("/api/v1/tasks/" + task["id"], headers=headers).json()["title"] == "Kept task"
    pref = r.json()
    assert (
        client.delete(
            "/api/v1/sender-preferences/faculty%40somaiya.edu?revision=" + str(pref["revision"]),
            headers=headers,
        ).status_code
        == 200
    )
    run(client, headers, conn)
    assert records(student.uid)[0].processing_state == "blocked"  # Unblocking alone does not reprocess.
    r = client.post(f"/api/v1/connections/{conn}/reprocess", headers=fresh(headers))
    job = r.json()["job"]
    while job["status"] not in ("completed", "failed"):
        job = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers).json()
    (record,) = records(student.uid)
    assert record.processing_state == "awaiting_interpretation" and record.title == "IA notice"


def test_sender_preferences_normalize_revise_and_isolate(client, headers):
    r = client.put(
        "/api/v1/sender-preferences/%20LMS-KJSSE%40Somaiya.EDU%20",
        headers=headers,
        json={"action": "include"},
    )
    assert r.status_code == 200 and r.json()["email"] == "lms-kjsse@somaiya.edu"
    path = "/api/v1/sender-preferences/lms-kjsse%40somaiya.edu"
    assert client.put(path, headers=headers, json={"action": "block"}).status_code == 409
    r = client.put(path, headers=headers, json={"action": "block", "revision": 1})
    assert r.json()["action"] == "block" and r.json()["revision"] == 2
    assert (
        client.put(
            "/api/v1/sender-preferences/not-an-email", headers=headers, json={"action": "block"}
        ).status_code
        == 422
    )
    assert client.put(path, headers=headers, json={"action": "allow"}).status_code == 422
    other = account()
    assert client.get("/api/v1/sender-preferences", headers=other.headers).json()["items"] == []
    assert client.delete(path + "?revision=2", headers=other.headers).status_code == 404
    items = client.get("/api/v1/sender-preferences", headers=headers).json()["items"]
    assert [(p["email"], p["action"]) for p in items] == [("lms-kjsse@somaiya.edu", "block")]


def iso(dt):
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def classroom_fixture(fake):
    recent, old = now() - timedelta(days=2), now() - timedelta(days=150)
    future = now() + timedelta(days=10)
    fake.courses = [
        {"id": "c-dbms", "name": "26-27 dbms Div B", "section": "B", "courseState": "ACTIVE"},
        {"id": "c-lab", "name": "DBMS B2 116A", "courseState": "ACTIVE"},
        {"id": "c-unmapped", "name": "Unlinked course", "courseState": "ACTIVE"},
    ]
    fake.coursework["c-dbms"] = [
        {
            "id": "w-recent",
            "title": "Experiment 8",
            "description": "Private instructions text",
            "workType": "ASSIGNMENT",
            "state": "PUBLISHED",
            "creationTime": iso(recent - timedelta(days=1)),
            "updateTime": iso(recent),
            "dueDate": {"year": future.year, "month": future.month, "day": future.day},
            "dueTime": {"hours": 18, "minutes": 29},
            "materials": [
                {
                    "driveFile": {
                        "driveFile": {"id": "d1", "title": "TCL.pdf", "alternateLink": "https://drive/x"}
                    }
                }
            ],
        },
        {
            "id": "w-future",
            "title": "Old future",
            "creationTime": iso(old),
            "updateTime": iso(old),
            "dueDate": {"year": future.year, "month": future.month, "day": future.day},
            "dueTime": {"hours": 1},
        },
        {
            "id": "w-outstanding",
            "title": "Old outstanding",
            "creationTime": iso(old),
            "updateTime": iso(old - timedelta(days=1)),
        },
        {
            "id": "w-done",
            "title": "Old done",
            "creationTime": iso(old),
            "updateTime": iso(old - timedelta(days=2)),
        },
    ]
    fake.submissions["c-dbms"] = [
        {
            "id": "s1",
            "courseWorkId": "w-done",
            "state": "TURNED_IN",
            "updateTime": iso(old),
            "submissionHistory": [{"stateHistory": {"state": "TURNED_IN", "stateTimestamp": iso(old)}}],
        },
        {"id": "s2", "courseWorkId": "w-outstanding", "state": "CREATED", "updateTime": iso(old)},
        {"id": "s3", "courseWorkId": "w-recent", "state": "NEW", "updateTime": iso(recent)},
    ]
    fake.announcements["c-dbms"] = [
        {
            "id": "a1",
            "text": "OST during the lab in the week of 5 October",
            "creationTime": iso(recent),
            "updateTime": iso(recent),
        },
        {"id": "a-old", "text": "Old", "creationTime": iso(old), "updateTime": iso(old)},
    ]


def test_classroom_discovery_explicit_mapping_and_initial_import_rules(client, headers, student, fake):
    theory = client.post("/api/v1/subjects", headers=headers, json={"name": "DBMS", "kind": "theory"}).json()
    lab = client.post("/api/v1/subjects", headers=headers, json={"name": "DBMS Lab", "kind": "lab"}).json()
    classroom_fixture(fake)
    conn = connect(client, headers, fake, "classroom")
    job = run(client, headers, conn)
    assert job["status"] == "completed"
    with transaction(student.uid) as db:
        assert db.scalar(select(func.count()).select_from(Subject)) == 2  # Discovery never creates subjects.
    courses = client.get(f"/api/v1/connections/{conn}/classroom-courses", headers=headers).json()["items"]
    assert {c["externalCourseId"] for c in courses} == {"c-dbms", "c-lab", "c-unmapped"}
    # Courses named by a subject's short form link themselves to every subject of that course;
    # "Unlinked course" matches none and is never read.
    assert "coursework:c-dbms" in fake.calls and "coursework:c-unmapped" not in fake.calls
    for subject in (theory, lab):
        mapped = client.get("/api/v1/subjects/" + subject["id"], headers=headers).json()["classroomMappings"]
        assert {m["externalCourseId"] for m in mapped} == {"c-dbms", "c-lab"}
        assert all(m["automatic"] for m in mapped)
    # Explicit linking still works and keeps kinds distinct.
    for subject in (theory, lab):
        r = client.put(
            f"/api/v1/subjects/{subject['id']}/classroom-mappings/{conn}/c-dbms", headers=fresh(headers)
        )
        assert r.status_code == 200 and r.json()["subjectKind"] == subject["kind"]
    assert (
        client.put(
            f"/api/v1/subjects/{theory['id']}/classroom-mappings/{conn}/missing", headers=fresh(headers)
        ).status_code
        == 404
    )
    subject = client.get("/api/v1/subjects/" + lab["id"], headers=headers).json()
    assert subject["kind"] == "lab" and "c-dbms" in {
        m["externalCourseId"] for m in subject["classroomMappings"]
    }
    assert "batch" not in json.dumps(subject["classroomMappings"]).lower()
    fake.calls.clear()
    job = run(client, headers, conn)
    assert job["status"] == "completed"
    assert "coursework:c-dbms" in fake.calls and "coursework:c-unmapped" not in fake.calls
    work = {r.provider_id.rsplit(":", 1)[1]: r for r in records(student.uid, kind="classroom_coursework")}
    assert set(work) == {"w-recent", "w-future", "w-outstanding"}
    recent = work["w-recent"]
    assert recent.data["dueAt"].endswith("18:29:00+00:00") and recent.title == "Experiment 8"
    assert "Private instructions text" not in json.dumps(recent.data)
    assert recent.provider_id == "classroom:google-sub-1:c-dbms:coursework:w-recent"
    assert {r.provider_id.rsplit(":", 1)[1] for r in records(student.uid, kind="classroom_announcement")} == {
        "a1"
    }
    assert len(records(student.uid, kind="classroom_submission")) == 3
    with transaction(student.uid) as db:
        (material,) = db.scalars(
            select(SourceAttachment).where(SourceAttachment.source_record_id == recent.id)
        )
        assert material.kind == "drive" and material.title == "TCL.pdf"
        assert db.scalar(select(func.count()).select_from(Task)) == 0

    # Incremental: an edited coursework item becomes a new processing revision; old items are not refetched.
    fake.coursework["c-dbms"][0] = {
        **fake.coursework["c-dbms"][0],
        "title": "Experiment 8 revised",
        "updateTime": iso(now()),
    }
    job = run(client, headers, conn)
    work = {r.provider_id.rsplit(":", 1)[1]: r for r in records(student.uid, kind="classroom_coursework")}
    assert work["w-recent"].revision == 2 and work["w-recent"].title == "Experiment 8 revised"
    assert job["progress"].get("updated") == 1

    # Source disappearance marks the mapping unavailable without changing records.
    fake.courses = [c for c in fake.courses if c["id"] != "c-dbms"]
    run(client, headers, conn)
    subject = client.get("/api/v1/subjects/" + theory["id"], headers=headers).json()
    gone = [m for m in subject["classroomMappings"] if m["externalCourseId"] == "c-dbms"]
    assert gone[0]["sourceAvailable"] is False
    assert len(records(student.uid, kind="classroom_coursework")) == 3

    # Removing a mapping stops future coursework reads for it.
    for s in (theory, lab):
        r = client.delete(
            f"/api/v1/subjects/{s['id']}/classroom-mappings/{conn}/c-dbms", headers=fresh(headers)
        )
        assert r.json()["removed"] is True
    fake.courses.append({"id": "c-dbms", "name": "26-27 dbms Div B"})
    fake.calls.clear()
    run(client, headers, conn)
    assert "coursework:c-dbms" not in fake.calls  # An unlinked course is never relinked automatically.


def test_cross_user_access_to_sources_is_rejected(client, headers, student, fake):
    classroom_fixture(fake)
    conn = connect(client, headers, fake, "classroom")
    job = run(client, headers, conn)
    other = account()
    s = client.post("/api/v1/subjects", headers=other.headers, json={"name": "Mine", "kind": "theory"}).json()
    for method, path in [
        ("get", f"/api/v1/connections/{conn}/classroom-courses"),
        ("get", f"/api/v1/sync-jobs/{job['id']}"),
        ("post", f"/api/v1/sync-jobs/{job['id']}/advance"),
        ("put", f"/api/v1/subjects/{s['id']}/classroom-mappings/{conn}/c-dbms"),
    ]:
        assert getattr(client, method)(path, headers={**other.headers}).status_code == 404
    assert client.post(f"/api/v1/connections/{conn}/sync", headers=other.headers, json={}).status_code == 404
    with transaction(other.uid) as db:
        assert db.scalar(select(func.count()).select_from(Connection)) == 0
        assert db.scalar(select(func.count()).select_from(OAuthGrant)) == 0


def test_expired_access_refreshes_rotates_key_and_revoked_grant_requires_reconnect(
    client, headers, student, fake
):
    fake.add_message("m1", eml("faculty@somaiya.edu", "Notice", "Body", "<n1@x>"))
    conn = connect(client, headers, fake)
    old = google.Vault(config["SOURCE_TOKEN_KEYS"], "v1")
    with transaction(student.uid) as db:
        grant = db.scalar(select(OAuthGrant))
        grant.refresh_token, grant.key_version = old.encrypt("refresh-c1"), "v1"
        grant.access_token, grant.access_expires_at = old.encrypt("stale"), now() - timedelta(seconds=1)
        db.commit()
    assert run(client, headers, conn)["status"] == "completed" and fake.refreshes == ["refresh-c1"]
    with transaction(student.uid) as db:
        assert db.scalar(select(OAuthGrant)).key_version == "v2"
        grant = db.scalar(select(OAuthGrant))
        grant.access_expires_at = now() - timedelta(seconds=1)
        db.commit()
    fake.refresh_error = "auth"
    job = run(client, headers, conn)
    assert job["status"] == "failed" and job["error"]["code"] == "RECONNECT_REQUIRED"
    listed = client.get("/api/v1/connections", headers=headers).json()["items"][0]
    assert listed["status"] == "needs_reauth" and listed["lastError"]["code"] == "RECONNECT_REQUIRED"
    # Reconnecting the same account reactivates the existing connection.
    fake.refresh_error = None
    assert connect(client, headers, fake, code="again") == conn
    assert client.get("/api/v1/connections", headers=headers).json()["items"][0]["status"] == "active"


def test_focus_trigger_respects_fifteen_minutes_but_manual_and_open_start(client, headers, fake):
    conn = connect(client, headers, fake)
    assert run(client, headers, conn, "open")["status"] == "completed"
    r = client.post(
        f"/api/v1/connections/{conn}/sync", headers=fresh(headers), json={"trigger": "focus"}
    ).json()
    assert r == {"job": None, "created": False, "skipped": "recent"}
    assert run(client, headers, conn, "manual")["status"] == "completed"


def test_disconnect_cancels_active_job_and_preserves_records(client, headers, student, fake):
    gmail_fixture(fake)
    conn = connect(client, headers, fake)
    run(client, headers, conn)
    job = client.post(f"/api/v1/connections/{conn}/sync", headers=fresh(headers), json={}).json()["job"]
    c = client.get("/api/v1/connections", headers=headers).json()["items"][0]
    key = fresh(headers)
    r = client.delete(f"/api/v1/connections/{conn}?revision={c['revision']}", headers=key)
    assert r.json()["cancelledJobs"] == 1 and r.json()["preservedSourceRecords"] == 5
    assert (
        client.delete(f"/api/v1/connections/{conn}?revision={c['revision']}", headers=key).json() == r.json()
    )
    assert client.get(f"/api/v1/sync-jobs/{job['id']}", headers=headers).json()["status"] == "cancelled"
    assert len(records(student.uid)) == 5


def test_reference_eml_through_import_pipeline(client, headers, student, fake):
    if not REFERENCE.exists():
        pytest.skip("reference archive not present")
    files = sorted(REFERENCE.glob("*.eml"))
    for i, f in enumerate(files):
        fake.add_message(f"r{i}", f.read_bytes(), ts=now() - timedelta(hours=i + 1))
    conn = connect(client, headers, fake)
    job = run(client, headers, conn, limit=200)
    assert job["status"] == "completed"
    states = [r.processing_state for r in records(student.uid)]
    # 22 exports are 11 distinct messages; each repeated export is detected as a duplicate occurrence.
    assert len(states) == 22 and states.count("duplicate") == 11
    assert datetime.now(UTC) - records(student.uid)[0].created_at < timedelta(minutes=5)


def test_single_consent_connects_gmail_and_classroom_and_reports_partial_grants(client, headers, fake):
    fake.service = "both"
    r = client.post("/api/v1/connections/authorize", headers=headers, json={})
    q = parse_qs(urlparse(r.json()["url"]).query)
    assert set(q["scope"][0].split()) == {
        "openid", "email", "profile", *google.SERVICE_SCOPES["gmail"], *google.SERVICE_SCOPES["classroom"]
    }  # fmt: skip
    state = q["state"][0]
    out = client.get(f"/api/v1/connections/oauth/callback?state={state}&code=both", headers=headers).json()
    assert out["services"] == ["gmail", "classroom"] and out["missing"] == {}
    listed = client.get("/api/v1/connections", headers=headers).json()["items"]
    assert sorted(c["service"] for c in listed) == ["classroom", "gmail"]
    assert len({c["account"]["id"] for c in listed}) == 1  # One Google account and grant, two connections.
    # Unchecking Classroom on Google's consent screen still connects Gmail and names what is missing.
    other = account()
    fake.scopes = ["openid", "email", "profile", *google.SERVICE_SCOPES["gmail"]]
    fake.identity_claims = {"sub": "partial-sub", "email": "p@somaiya.edu", "email_verified": True}
    state = parse_qs(
        urlparse(
            client.post("/api/v1/connections/authorize", headers=other.headers, json={}).json()["url"]
        ).query
    )["state"][0]
    out = client.get(
        f"/api/v1/connections/oauth/callback?state={state}&code=partial", headers=other.headers
    ).json()
    assert out["services"] == ["gmail"] and set(out["missing"]) == {"classroom"}
    assert fake.revoked == []


def test_sign_in_grants_gmail_and_classroom_without_separate_connect(client, student, fake):
    gateway = {"x-gateway-secret": config["GATEWAY_SECRET"]}
    start = client.post("/internal/auth/start", headers=gateway, json={}).json()
    q = parse_qs(urlparse(start["url"]).query)
    assert {*google.SERVICE_SCOPES["gmail"], *google.SERVICE_SCOPES["classroom"]} <= set(
        q["scopes"][0].split()
    )
    assert q["access_type"] == ["offline"] and q["prompt"] == ["select_account"]
    assert parse_qs(
        urlparse(
            client.post("/internal/auth/start", headers=gateway, json={"consent": True}).json()["url"]
        ).query
    )["prompt"] == ["consent"]
    scopes = " ".join(["openid", *google.SERVICE_SCOPES["gmail"], *google.SERVICE_SCOPES["classroom"]])
    fake.token_details = {
        "aud": config["GOOGLE_OAUTH_CLIENT_ID"],
        "sub": "somaiya-sub",
        "email": "student@somaiya.edu",
        "scope": scopes,
        "expires_in": 3500,
    }

    def sign_in(provider_refresh):
        start = client.post("/internal/auth/start", headers=gateway, json={}).json()
        auth.provider.next_tokens = {
            "access_token": student.token,
            "refresh_token": "supabase-refresh",
            "provider_token": "google-access",
            "provider_refresh_token": provider_refresh,
        }
        r = client.post(
            "/internal/auth/callback", headers=gateway, json={"state": start["state"], "code": "c"}
        )
        assert r.status_code == 200
        return {**gateway, "x-session": r.json()["session"]}

    h = sign_in("google-refresh")
    items = client.get("/api/v1/connections", headers=h).json()["items"]
    assert sorted((c["service"], c["status"]) for c in items) == [
        ("classroom", "active"),
        ("gmail", "active"),
    ]
    with transaction(student.uid) as db:
        grant = db.scalar(select(OAuthGrant))
        assert google.vault().decrypt(grant.refresh_token, grant.key_version) == "google-refresh"
    # A later sign-in without a new refresh token keeps the stored grant.
    h = sign_in(None)
    with transaction(student.uid) as db:
        grant = db.scalar(select(OAuthGrant))
        assert google.vault().decrypt(grant.refresh_token, grant.key_version) == "google-refresh"
    # A token for another OAuth client cannot be used for syncing; sign-in still succeeds.
    other = account("second@somaiya.edu")
    fake.token_details = {
        **fake.token_details,
        "aud": "someone-else.apps.googleusercontent.com",
        "email": "second@somaiya.edu",
    }
    start = client.post("/internal/auth/start", headers=gateway, json={}).json()
    auth.provider.next_tokens = {
        "access_token": other.token,
        "refresh_token": "r",
        "provider_token": "t",
        "provider_refresh_token": "x",
    }
    r = client.post("/internal/auth/callback", headers=gateway, json={"state": start["state"], "code": "c"})
    assert r.status_code == 200
    assert client.get("/api/v1/connections", headers=other.headers).json()["items"] == []


def test_streaming_duplicate_survives_minimized_original(client, headers, student, fake, monkeypatch):
    raw = eml("teacher@somaiya.edu", "Campus newsletter", "Campus news", "<stream-copy@example.test>")
    fake.add_message("original", raw, ts=now())
    fake.add_message("copy", raw, ts=now() - timedelta(minutes=1))
    metadata = fake.gmail_metadata

    def after_interpretation(token, gid):
        if gid == "copy":
            timeout = time.monotonic() + 10
            while time.monotonic() < timeout:
                saved = records(student.uid)
                if saved and saved[0].processing_state == "ignored":
                    assert saved[0].content_hash is None and saved[0].data == {}
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("original was not interpreted while importing")
        return metadata(token, gid)

    monkeypatch.setattr(fake, "gmail_metadata", after_interpretation)
    monkeypatch.setattr(settings(), "sync_work_budget_seconds", 30)
    conn = connect(client, headers, fake)
    job = run(client, headers, conn)
    assert job["status"] == "completed", job
    states = {r.provider_id.rsplit(":", 1)[1]: r.processing_state for r in records(student.uid)}
    assert states == {"original": "ignored", "copy": "duplicate"}
    with transaction(student.uid) as db:
        assert "messageFingerprints" not in db.get(SyncJob, job["id"]).checkpoint


def test_gmail_30_day_window_applies_to_initial_import_and_history(client, headers, student, fake):
    for name, age in [("old", 31), ("recent", 29), ("newest", 1)]:
        fake.add_message(
            name,
            eml("teacher@somaiya.edu", "Campus news", "News", f"<{name}@window.test>"),
            ts=now() - timedelta(days=age),
        )
    conn = connect(client, headers, fake)
    assert run(client, headers, conn)["status"] == "completed"
    assert {r.provider_id.rsplit(":", 1)[1] for r in records(student.uid)} == {"recent", "newest"}
    assert "gmail_raw:old" not in fake.calls
    fake.calls.clear()
    fake.add_message(
        "old-history",
        eml("teacher@somaiya.edu", "Old mail", "News", "<old-history@window.test>"),
        ts=now() - timedelta(days=40),
    )
    fake.add_message("fresh", eml("teacher@somaiya.edu", "Fresh mail", "News", "<fresh@window.test>"))
    job = run(client, headers, conn)
    assert job["status"] == "completed" and job["progress"]["outsideWindow"] == 1
    assert "gmail_raw:old-history" not in fake.calls
    assert fake.calls.index("gmail_list") < fake.calls.index("gmail_history")


def test_existing_90_day_gmail_job_restarts_inside_30_day_window(client, headers, student, fake):
    fake.add_message(
        "old", eml("teacher@somaiya.edu", "Old", "News", "<old@window.test>"), ts=now() - timedelta(days=40)
    )
    fake.add_message("new", eml("teacher@somaiya.edu", "New", "News", "<new@window.test>"))
    conn = connect(client, headers, fake)
    job = client.post(f"/api/v1/connections/{conn}/sync", headers=fresh(headers), json={}).json()["job"]
    with transaction(student.uid) as db:
        row = db.get(SyncJob, job["id"])
        row.checkpoint = {
            "stage": "listing",
            "source": "list",
            "query": f"after:{int((now() - timedelta(days=90)).timestamp())}",
            "pending": ["old"],
            "more": True,
        }
        db.commit()
    assert run(client, headers, conn)["status"] == "completed"
    assert "gmail_raw:old" not in fake.calls
    assert len(records(student.uid)) == 1
