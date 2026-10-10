"""Phase 3: interpretation, academic targeting, review, rules, reconciliation, and completion.

Fixtures are synthetic, redacted messages modelled on the catalogued LMS templates and faculty
notices (specification section 6). The AI provider is faked; no external calls are made.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from urllib.parse import quote

import pytest
from sqlalchemy import delete, func, select

from duecare import ai, google, interpret, sync, targeting
from duecare.config import settings
from duecare.db import transaction
from duecare.domain import effective_status
from duecare.models import History, ReviewItem, SourceEvent, Task, now
from tests.fake_google import FakeGoogle, eml
from tests.test_phase1 import PROFILE
from tests.test_phase2 import connect, fresh, records, run

LMS = "lms-kjsse@somaiya.edu"
HOST = "https://lms-kjsce.somaiya.edu"
AUTH = (
    "Authentication-Results",
    "mx.google.com; dkim=pass header.i=@somaiya.edu; spf=pass smtp.mailfrom=lms-kjsse@somaiya.edu; "
    "dmarc=pass (p=NONE) header.from=somaiya.edu",
)
REFERENCE = Path(__file__).resolve().parents[3] / "docs/reference-files/emails"


class FakeAI:
    def __init__(self):
        self.items, self.calls, self.down = {}, [], False
        self.timings, self.timing_calls = {}, []

    def timing(self, payload):
        """Timing-only look: answers keyed by item title; anything unlisted states no date."""
        self.timing_calls.append([i["title"] for i in payload["items"]])
        if self.down:
            raise ai.AIUnavailable("AI providers are temporarily unavailable")
        items = [
            {"key": i["key"], **self.timings.get(i["title"], {"kind": "none"})} for i in payload["items"]
        ]
        return ai.TimingResolution.model_validate({"items": items}), {"provider": "fake", "model": "fake-1"}

    def __call__(self, payload):
        # Classroom announcements have no title: they are keyed by their text.
        key = (
            payload["source"].get("subject")
            or payload["source"].get("title")
            or payload["sections"][0]["text"]
        )
        self.calls.append(key)
        if self.down:
            raise ai.AIUnavailable("AI providers are temporarily unavailable")
        items = self.items.get(key, [])
        items = items(payload) if callable(items) else items
        return ai.Extraction.model_validate({"items": items}), {"provider": "fake", "model": "fake-1"}


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    provider = FakeGoogle()
    monkeypatch.setattr(google, "provider", provider)
    return provider


@pytest.fixture(autouse=True)
def model(monkeypatch):
    fake_ai = FakeAI()
    monkeypatch.setattr(ai, "extract", fake_ai)
    monkeypatch.setattr(ai, "resolve_timing", fake_ai.timing)
    return fake_ai


@pytest.fixture
def auto(monkeypatch):
    monkeypatch.setattr(settings(), "auto_completion_paths", "lms_assignment_receipt,classroom_turned_in")


def setup_student(client, headers, batch="2"):
    me = client.get("/api/v1/me", headers=headers).json()
    client.patch(
        "/api/v1/me", headers=headers, json={**PROFILE, "generalBatch": batch, "revision": me["revision"]}
    )
    out = {}
    for name, kind, extra in [
        ("Data Structures", "theory", {"code": "16U2602"}),
        ("Data Structures Laboratory", "lab", {"code": "16U2603"}),
        ("Integral Transforms and Vector Calculus", "theory", {"aliases": ["ITVC"]}),
        ("Computer Organization & Architecture", "theory", {"aliases": ["COA"]}),
        ("Discrete Mathematics", "theory", {"aliases": ["DSM"]}),
        ("Web Development Laboratory", "lab", {"aliases": ["WDL"]}),
    ]:
        out[name] = client.post(
            "/api/v1/subjects", headers=headers, json={"name": name, "kind": kind, **extra}
        ).json()
    return out


def reminder(
    title,
    when,
    aid,
    kind="Assignment",
    course="Data Structures_B_ODD_26-27",
    prefix="DS_B_ODD_26-27",
    overdue=False,
):
    verb = "is due" if kind == "Assignment" else "closes"
    subject = f"[LMS-Reminder] {'OVERDUE: ' if overdue else ''}({prefix}-{kind}) {title} {verb}"
    act = "assign" if kind == "Assignment" else "quiz"
    body = f"{subject}\n\nWhen | {when}\n\nCourse | {course}\n\nActivity | {kind}: {title}\n\n{HOST}/mod/{act}/view.php?id={aid}\n"
    return subject, body


def receipt(title, crumb, aid, filename):
    subject = f"Assignment submission confirmation - {title}"
    body = (
        f"{crumb} -> Assignment -> {title}\n-----\nYou have submitted an assignment submission for '{title}'.\n\n"
        f"You can see the status of your assignment submission:\n\n{HOST}/mod/assign/view.php?id={aid}\n\n"
        f"Your submission contains:\n\nFile submissions\n* {filename} (80 KB)\n"
    )
    return subject, body


def overdue(title, course, due, aid):
    subject = f"Overdue: {title}"
    body = (
        f"Hi STUDENT,\n\n{title} in course {course} was due on {due}.\n\nYou might still be able to submit your "
        f"assignment, but your submission will be marked as late.\n\nGo to activity [1]\n\nLinks:\n------\n"
        f"[1] {HOST}/mod/assign/view.php?id={aid}&action=view\n"
    )
    return subject, body


def send(fake, gid, sender, subject_body, sent, headers=(), to="student@somaiya.edu"):
    subject, body = subject_body
    fake.add_message(
        # Historical template dates remain source evidence; the fixture delivers old
        # examples within the current Gmail window rather than testing retention here.
        gid,
        eml(sender, subject, body, f"<{gid}@test>", sent=sent, headers=headers, to=to),
        ts=max(sent, now() - timedelta(days=29)),
    )


def tasks(uid):
    with transaction(uid) as db:
        return list(db.scalars(select(Task).where(Task.user_id == uid).order_by(Task.created_at)))


def reviews(client, headers, status="open"):
    return client.get("/api/v1/review-items?status=" + status, headers=headers).json()["items"]


def resolve(client, headers, item, **body):
    r = client.post(
        f"/api/v1/review-items/{item['id']}/resolve",
        headers=fresh(headers),
        json={"revision": item["revision"], **body},
    )
    assert r.status_code == 200, r.text
    return r.json()


def ist(y, m, d, h, mi):
    return datetime(y, m, d, h, mi, tzinfo=UTC) - timedelta(hours=5, minutes=30)


def test_targeting_normalization_and_outcomes():
    profile = {**PROFILE}
    merged = targeting.merge(targeting.parse_course_label("ITVC_A-B-C-D_SY_ODD_26-27"))
    assert (
        targeting.evaluate(merged, profile, trusted=True)[0] == "applicable"
    )  # A-B-C-D includes Division B.
    b2 = targeting.merge({"batches": ["B2"], "scope": "activity"})
    assert targeting.evaluate(b2, profile, subject_kind="lab")[0] == "applicable"  # B + batch 2 = B2.
    assert targeting.evaluate(b2, {**profile, "generalBatch": "1"}, subject_kind="lab")[0] == "mismatch"
    broad_b1 = targeting.merge(
        targeting.parse_course_label("ITVC_A-B-C-D_SY_ODD_26-27"), {"batches": ["B1"], "scope": "activity"}
    )
    assert targeting.evaluate(broad_b1, profile, trusted=True)[0] == "mismatch"  # Activity qualifier wins.
    assert targeting.batch_labels("Room B115A for B2 Batch") == ["B2"]  # Room codes are not batches.
    assert (
        targeting.evaluate(targeting.merge({"classYears": ["TY"], "scope": "activity"}), profile)[0]
        == "mismatch"
    )
    assert (
        targeting.evaluate(
            targeting.merge({"semesters": ["III"], "divisions": ["B"], "scope": "activity"}), profile
        )[0]
        == "applicable"
    )
    assert targeting.evaluate(targeting.merge({}), profile, subject_kind="lab")[0] == "review"
    assert (
        targeting.evaluate(
            targeting.merge({"conditional": True, "scope": "activity"}), profile, trusted=True
        )[0]
        == "review"
    )


def test_exp6_lms_flow_review_alias_receipts_and_completion_precedence(client, headers, student, fake, auto):
    subjects = setup_student(client, headers)
    when = "Monday, 21 September 2026 11:59 PM IST"
    send(fake, "e13", LMS, reminder("EXP6-BST", when, 91022), ist(2026, 9, 21, 0, 1))
    conn = connect(client, headers, fake)
    job = run(client, headers, conn)
    assert job["status"] == "completed" and not job["progress"].get("reviews"), job["progress"]
    # "Data Structures" names both the theory and the lab subject; "EXP6" is lab work, so the lab is
    # linked automatically without asking.
    assert reviews(client, headers) == []
    (task,) = tasks(student.uid)
    assert str(task.subject_id) == subjects["Data Structures Laboratory"]["id"]
    assert task.data["subjectLink"] == {"method": "name"}
    assert task.type == "assignment" and task.due_at == ist(2026, 9, 21, 23, 59)
    assert effective_status(task, now()) == "missed"

    # The overdue notice and a later receipt for the same activity link to the same task.
    send(
        fake,
        "e21",
        LMS,
        overdue("EXP6-BST", "Data Structures_B_ODD_26-27", "MONDAY, 21 SEPTEMBER 2026, 11:59 PM", 91022),
        ist(2026, 9, 22, 0, 10),
    )
    send(
        fake,
        "e17",
        LMS,
        receipt("EXP6-BST", "DS_B_ODD_26-27", 91022, "EXP 6 v1.docx"),
        ist(2026, 9, 25, 18, 1),
        [AUTH],
    )
    send(
        fake,
        "e16",
        LMS,
        receipt("EXP6-BST", "DS_B_ODD_26-27", 91022, "EXP 6.docx"),
        ist(2026, 10, 6, 10, 44),
        [AUTH],
    )
    run(client, headers, conn)
    (task,) = tasks(student.uid)  # No duplicate task from notices or receipts.
    assert task.completed_at and task.data["completion"]["origin"] == "lms_assignment_receipt"
    with transaction(student.uid) as db:
        submissions = db.scalars(select(SourceEvent).where(SourceEvent.event_type == "submission")).all()
        assert len(submissions) == 2  # Two distinct receipt events for one activity.
    evidence = client.get(f"/api/v1/tasks/{task.id}/evidence", headers=headers).json()["items"]
    assert {e["eventType"] for e in evidence} == {"due_notice", "submission"} and len(evidence) == 4

    # A synthetic later overdue reminder (labelled synthetic) cannot reopen or duplicate completed work.
    send(
        fake,
        "synthetic-later",
        LMS,
        overdue("EXP6-BST", "Data Structures_B_ODD_26-27", "MONDAY, 21 SEPTEMBER 2026, 11:59 PM", 91022),
        now(),
    )
    run(client, headers, conn)
    (task,) = tasks(student.uid)
    assert task.completed_at and effective_status(task, now() + timedelta(days=30)) == "completed"
    assert reviews(client, headers) == []
    api_task = client.get(f"/api/v1/tasks/{task.id}", headers=headers).json()
    assert api_task["status"] == "completed" and api_task["source"] == "gmail"


def test_unverified_receipts_ask_once_and_invalid_receipts_never_complete(client, headers, student, fake):
    subjects = setup_student(client, headers)
    send(
        fake,
        "d1",
        LMS,
        reminder("EXP7-Graph", "Monday, 12 October 2026 11:59 PM IST", 92000),
        now() - timedelta(days=2),
    )
    conn = connect(client, headers, fake)
    run(client, headers, conn)
    (task,) = tasks(student.uid)  # Linked to the DS lab automatically.
    assert str(task.subject_id) == subjects["Data Structures Laboratory"]["id"]
    send(
        fake,
        "r1",
        LMS,
        receipt("EXP7-Graph", "DS_B_ODD_26-27", 92000, "a.docx"),
        now() - timedelta(days=1),
        [],
    )
    send(
        fake,
        "r2",
        LMS,
        receipt("EXP7-Graph", "DS_B_ODD_26-27", 92000, "b.docx"),
        now() - timedelta(hours=5),
        [],
    )
    # Forwarded copy and a spoofed sender: never automatic completion.
    send(
        fake,
        "fw",
        LMS,
        (
            "Fwd: " + receipt("EXP7-Graph", "DS_B_ODD_26-27", 92000, "c")[0],
            receipt("EXP7-Graph", "DS_B_ODD_26-27", 92000, "c")[1],
        ),
        now() - timedelta(hours=4),
        [AUTH],
    )
    send(
        fake,
        "spoof",
        "lms-kjsse@somaiya.edu.attacker.test",
        receipt("EXP7-Graph", "DS_B_ODD_26-27", 92000, "d"),
        now() - timedelta(hours=3),
    )
    run(client, headers, conn)
    (task,) = tasks(student.uid)
    assert task.completed_at is None
    open_items = reviews(client, headers)
    confirm = [r for r in open_items if r["issueType"] == "receipt_unverified"]
    assert len(confirm) == 1 and confirm[0]["evidenceCount"] == 2
    assert "gmail_raw:spoof" not in google.provider.calls  # Not an academic sender: body never fetched.
    resolve(client, headers, confirm[0], action="complete")
    (task,) = tasks(student.uid)
    assert task.completed_at and task.data["completion"]["origin"] == "student_confirmed_evidence"


def test_reopen_survives_replay_of_older_receipt(client, headers, student, fake, auto):
    subjects = setup_student(client, headers)
    send(
        fake,
        "d1",
        LMS,
        reminder("EXP8-Heap", "Monday, 19 October 2026 11:59 PM IST", 93000),
        now() - timedelta(days=3),
    )
    send(
        fake,
        "r1",
        LMS,
        receipt("EXP8-Heap", "DS_B_ODD_26-27", 93000, "x.docx"),
        now() - timedelta(days=2),
        [AUTH],
    )
    conn = connect(client, headers, fake)
    run(client, headers, conn)
    (task,) = tasks(student.uid)
    assert str(task.subject_id) == subjects["Data Structures Laboratory"]["id"]
    assert task.completed_at  # The reminder's task, linked automatically, is completed by the receipt.
    t = client.get(f"/api/v1/tasks/{task.id}", headers=headers).json()
    t = client.patch(
        f"/api/v1/tasks/{task.id}", headers=fresh(headers), json={"revision": t["revision"], "status": "due"}
    ).json()
    assert t["status"] == "due"
    r = client.post(f"/api/v1/connections/{conn}/reprocess", headers=fresh(headers))
    job = r.json()["job"]
    while job["status"] not in ("completed", "failed"):
        job = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers).json()
    (task,) = tasks(student.uid)
    assert task.completed_at is None  # The student's newer reopen wins over the older receipt.


def test_distinct_activities_quiz_window_and_fixed_session_close(client, headers, student, fake, auto):
    subjects = setup_student(client, headers)
    due = ("Due on Monday, 5 October 2026, 10:06 AM: Exp 5- Doubly LL, Circular LL",
           f"Hi STUDENT,\n\nThe assignment EXP 5- DOUBLY LL, CIRCULAR LL in course Data Structures_B_ODD_26-27 is due soon.\n\n"
           f"DUE: MONDAY, 5 OCTOBER 2026, 10:06 AM\n\nGo to activity [1]\n\nLinks:\n------\n[1] {HOST}/mod/assign/view.php?id=91542&action=view\n")  # fmt: skip
    quiz = ("Opens on Saturday, 5 September 2026, 8:00 PM: IA -1_5th September 2026 8 pm",
            "Hi STUDENT,\n\nThe quiz IA -1_5TH SEPTEMBER 2026 8 PM in course Integral Transforms and Vector "
            "Calculus_A-B-C-D_SY_ODD_26-27 is opening soon. OPENS: SATURDAY, 5\nSEPTEMBER 2026, 8:00 PM\n\n"
            f"CLOSES: SATURDAY, 5 SEPTEMBER 2026, 9:00 PM\n\nGo to quiz [1]\n\nLinks:\n------\n[1] {HOST}/mod/quiz/view.php?id=90115\n")  # fmt: skip
    send(fake, "e19", LMS, due, now() - timedelta(days=4))
    send(fake, "e20", LMS, quiz, now() - timedelta(days=30))
    send(
        fake, "e17", LMS, receipt("EXP6-BST", "DS_B_ODD_26-27", 91022, "x"), now() - timedelta(days=2), [AUTH]
    )
    conn = connect(client, headers, fake)
    run(client, headers, conn)
    for item in reviews(client, headers):
        resolve(
            client, headers, item, action="accept", subjectId=subjects["Data Structures Laboratory"]["id"]
        )
    by_title = {t.title: t for t in tasks(student.uid)}
    exp5 = by_title["Exp 5- Doubly LL, Circular LL"]
    assert (
        exp5.due_at == ist(2026, 10, 5, 10, 6) and not exp5.completed_at
    )  # EXP6 receipt cannot complete EXP5.
    q = by_title["IA -1_5th September 2026 8 pm"]
    assert (
        q.type == "test" and q.data["timingMode"] == "attempt_window" and q.due_at == ist(2026, 9, 5, 21, 0)
    )
    assert effective_status(q, ist(2026, 9, 5, 20, 59) + timedelta(seconds=59)) == "due"
    assert effective_status(q, ist(2026, 9, 5, 21, 0)) == "missed"
    assert len(tasks(student.uid)) == 2  # The unmatched EXP6 receipt created no task.
    assert [r for r in records(student.uid) if r.reason == "unmatched_receipt"]


def test_ai_notices_targeting_windows_rules_and_similarity(client, headers, student, fake, model):
    subjects = setup_student(client, headers)
    lab, wdl = subjects["Data Structures Laboratory"]["id"], subjects["Web Development Laboratory"]["id"]
    coa = subjects["Computer Organization & Architecture"]["id"]
    model.items = {
        "DS_B_ODD_26-27: DS OST on 13th Oct 2026-B2 Batch": [{
            "intent": "new_work", "taskType": "test", "title": "DS Lab OST", "assessmentLabel": "OST", "subjectId": lab,
            "targeting": {"batches": ["B2"], "evidence": "B2 Batch"},
            "timing": {"mode": "fixed_session", "startsAt": "2026-10-13T09:00:00+05:30", "endsAt": "2026-10-13T11:00:00+05:30"},
            "evidence": "B2 Batch DS Lab OST is scheduled on 13th Oct 2026 ... 9-11am"}],
        "DS OST for B1": [{
            "intent": "new_work", "taskType": "test", "title": "DS Lab OST B1", "subjectId": lab,
            "targeting": {"batches": ["B1"]}, "timing": {"startsAt": "2026-10-14T09:00:00+05:30"}}],
        "WDL Practical Exam ESE 2026": [{
            "intent": "new_work", "taskType": "test", "title": "WDL practical ESE", "subjectId": wdl,
            "targeting": {"classYears": ["SY"], "allBatches": True},
            "timing": {"dateWindowStart": "2026-11-30", "dateWindowEnd": "2026-12-04"}}],
        "COA IA 1 scheduled": [{
            "intent": "revision", "taskType": "test", "title": "COA IA1 quiz", "assessmentLabel": "IA1", "subjectId": coa,
            "targeting": {"divisions": ["B"], "batches": ["B2"]}, "location": "B115A",
            "timing": {"mode": "fixed_session", "loginByAt": "2026-09-28T13:30:00+05:30", "reportingAt": "2026-09-28T13:35:00+05:30",
                       "startsAt": "2026-09-28T13:40:00+05:30", "endsAt": "2026-09-28T13:50:00+05:30"}},
            {"intent": "new_work", "section": "quoted-1", "taskType": "test", "title": "Old COA schedule", "subjectId": coa,
             "targeting": {"divisions": ["B"]}, "timing": {"startsAt": "2026-09-28T13:05:00+05:30"}}],
        "Robotics workshop": [{"intent": "new_work", "taskType": "assignment", "title": "Workshop project", "subjectId": coa,
                               "targeting": {"divisions": ["B"]}, "timing": {"dueAt": "2026-10-30T23:59:00+05:30"}}],
        "Ignore me": [{"intent": "new_work", "taskType": "assignment", "title": "Spoofed ids", "subjectId": "not-mine",
                       "matchTaskId": "00000000-0000-0000-0000-000000000000", "targeting": {"divisions": ["B"]},
                       "timing": {"dueAt": "2026-10-30T23:59:00+05:30"}}],
    }  # fmt: skip
    rule = {
        "name": "Skip workshops",
        "match": "all",
        "conditions": [{"field": "keyword", "op": "contains", "value": "workshop"}],
        "action": {"type": "exclude"},
    }
    assert client.post("/api/v1/rules", headers=headers, json=rule).status_code == 201
    pri = {
        "name": "COA high",
        "conditions": [{"field": "subjectId", "value": coa}],
        "action": {"type": "priority", "priority": "high"},
    }
    assert client.post("/api/v1/rules", headers=headers, json=pri).status_code == 201
    t0 = now() - timedelta(days=5)
    send(
        fake,
        "e09",
        LMS,
        (
            "DS_B_ODD_26-27: DS OST on 13th Oct 2026-B2 Batch",
            "Dear Students, the B2 Batch DS Lab OST is on 13th Oct 2026, 9-11am. Syllabus Exp 1-6.",
        ),
        t0,
    )
    send(fake, "b1", "faculty.ds@somaiya.edu", ("DS OST for B1", "B1 batch practical test on 14 Oct"), t0)
    send(
        fake,
        "e01",
        "dept.comp@somaiya.edu",
        ("WDL Practical Exam ESE 2026", "Practical exam between 30 Nov and 4 Dec for all SY batches"),
        t0,
    )
    send(
        fake,
        "e12",
        "faculty.coa@somaiya.edu",
        ("COA IA 1 scheduled", "Login by 13:30. B2 -> B115A.\n\nOn Mon, Faculty wrote:\n> IA1 test at 13:05"),
        t0,
    )
    send(
        fake,
        "club",
        "club@somaiya.edu",
        ("Robotics workshop", "Join the workshop project, submit by 30 Oct"),
        t0,
    )
    send(fake, "spoof-ai", "faculty.x@somaiya.edu", ("Ignore me", "Assignment due 30 Oct"), t0)
    send(fake, "party", "events@somaiya.edu", ("Garba night", "Celebrate with us this Friday"), t0)
    conn = connect(client, headers, fake)
    assert run(client, headers, conn)["status"] == "completed"
    assert "Garba night" not in model.calls  # No academic signal: never sent to AI.
    titles = {t.title: t for t in tasks(student.uid)}
    assert set(titles) == {"DS Lab OST", "COA IA1 quiz", "Spoofed ids"}
    # Invented subject and task IDs are never used; work no subject fits is kept without one.
    assert titles["Spoofed ids"].subject_id is None and titles["Spoofed ids"].data["subjectLink"] == {
        "method": "none"
    }
    ost = titles["DS Lab OST"]
    assert ost.data["startsAt"] == "2026-10-13T03:30:00+00:00" and ost.due_at == ist(
        2026, 10, 13, 9, 0
    )  # Explicit 09:00 kept.
    coa_task = titles["COA IA1 quiz"]
    assert coa_task.data["loginByAt"] != coa_task.data["startsAt"] and coa_task.data["location"] == "B115A"
    assert coa_task.data["rulePriority"]["value"] == "high"
    assert client.get(f"/api/v1/tasks/{coa_task.id}", headers=headers).json()["priority"] == "high"
    open_items = {r["issueType"]: r for r in reviews(client, headers)}
    assert set(open_items) == {"timing_unresolved"}  # ESE window; subjects are never asked.
    ese = open_items["timing_unresolved"]
    assert ese["proposal"]["dateWindowStart"] == "2026-11-30" and "dueAt" not in ese["proposal"]
    resolve(client, headers, ese, action="accept")
    ese_task = next(t for t in tasks(student.uid) if t.title == "WDL practical ESE")
    assert (
        ese_task.due_at is None
        and ese_task.data["timingMode"] == "unresolved"
        and ese_task.data["dateWindowEnd"] == "2026-12-04"
    )
    # Mismatched B1 notice: no task, no review, minimal ignored record.
    b1 = next(r for r in records(student.uid) if r.provider_id.endswith(":b1"))
    assert b1.processing_state == "ignored" and b1.reason == "targeting_mismatch" and b1.title is None
    with transaction(student.uid) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ReviewItem)
                .where(ReviewItem.data["sourceTitle"].astext == "DS OST for B1")
            )
            == 0
        )


def test_blocked_queued_mail_and_ai_outage_pause_then_resume(client, headers, student, fake, model):
    subjects = setup_student(client, headers)
    coa = subjects["Computer Organization & Architecture"]["id"]
    model.items = {"COA assignment 2": [{"intent": "new_work", "taskType": "assignment", "title": "COA assignment 2",
                                         "subjectId": coa, "targeting": {"divisions": ["B"]},
                                         "timing": {"dueAt": "2026-11-02T23:59:00+05:30"}}]}  # fmt: skip
    send(
        fake,
        "a",
        "faculty.coa@somaiya.edu",
        ("COA assignment 2", "Submit assignment 2 by 2 Nov"),
        now() - timedelta(days=1),
    )
    send(
        fake,
        "b",
        "noisy.faculty@somaiya.edu",
        ("Quiz announcement", "Quiz next week"),
        now() - timedelta(days=1),
    )
    send(
        fake,
        "d",
        LMS,
        reminder("EXP9", "Monday, 26 October 2026 11:59 PM IST", 94000),
        now() - timedelta(days=1),
    )
    model.down = True
    conn = connect(client, headers, fake)
    job = run(client, headers, conn)
    assert job["status"] == "waiting_retry" and job["progress"]["aiPaused"] == 2
    assert job["error"]["code"] == "AI_UNAVAILABLE" and job["nextRetryAt"]
    # Template work continued without AI and linked its subject by name; AI items paused.
    assert reviews(client, headers) == []
    assert [(t.title, str(t.subject_id)) for t in tasks(student.uid)] == [
        ("EXP9", subjects["Data Structures Laboratory"]["id"])
    ]
    # Block one paused sender: its content is never sent to AI or applied.
    client.put(
        "/api/v1/sender-preferences/" + quote("noisy.faculty@somaiya.edu"),
        headers=headers,
        json={"action": "block"},
    )
    model.down, model.calls = False, []
    with transaction(student.uid) as db:
        for r in db.scalars(select(interpret.SourceRecord)):
            r.data = {k: v for k, v in r.data.items() if k != "aiPausedUntil"}
        pending_job = db.scalar(select(sync.SyncJob).where(sync.SyncJob.id == job["id"]))
        pending_job.next_retry_at = now() - timedelta(seconds=1)
        db.commit()
    resumed = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers)
    assert resumed.status_code == 200 and resumed.json()["status"] == "completed"
    assert "Quiz announcement" not in model.calls and "COA assignment 2" in model.calls
    assert sorted(t.title for t in tasks(student.uid)) == ["COA assignment 2", "EXP9"]


def test_classroom_turned_in_reclaimed_returned_and_materials(client, headers, student, fake, model, auto):
    setup_student(client, headers)
    dbms = client.post("/api/v1/subjects", headers=headers, json={"name": "DBMS", "kind": "theory"}).json()
    recent = (now() - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    later = (now() - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    fake.courses = [{"id": "c1", "name": "26-27 dbms Div B"}]
    fake.coursework["c1"] = [
        {"id": "w1", "title": "IA2.14 normalization", "description": "Solve", "workType": "ASSIGNMENT", "creationTime": recent,
         "updateTime": recent, "dueDate": {"year": 2026, "month": 10, "day": 1}, "dueTime": {"hours": 18, "minutes": 29}},
        {"id": "w2", "title": "Sample paper", "description": "Reference only", "workType": "MATERIAL", "creationTime": recent, "updateTime": recent},
        {"id": "w3", "title": "Experiment 8", "description": "TCL", "workType": "ASSIGNMENT", "creationTime": recent, "updateTime": recent,
         "dueDate": {"year": 2026, "month": 10, "day": 11}, "dueTime": {"hours": 18, "minutes": 29}},
    ]  # fmt: skip
    fake.submissions["c1"] = [
        {"id": "s1", "courseWorkId": "w1", "state": "TURNED_IN", "updateTime": recent,
         "submissionHistory": [{"stateHistory": {"state": "TURNED_IN", "stateTimestamp": recent}}]},
        {"id": "s3", "courseWorkId": "w3", "state": "RETURNED", "updateTime": recent},
    ]  # fmt: skip
    model.items = {
        "IA2.14 normalization": [{"intent": "new_work", "taskType": "assignment", "title": "IA2.14 normalization", "assessmentLabel": "IA2.14", "subjectId": dbms["id"]}],
        "Sample paper": [{"intent": "supporting", "title": "Sample paper"}],
        "Experiment 8": [{"intent": "new_work", "taskType": "assignment", "title": "Experiment 8", "subjectId": dbms["id"]}],
    }  # fmt: skip
    conn = connect(client, headers, fake, "classroom")
    run(client, headers, conn)
    client.put(f"/api/v1/subjects/{dbms['id']}/classroom-mappings/{conn}/c1", headers=fresh(headers))
    run(client, headers, conn)
    by_title = {t.title: t for t in tasks(student.uid)}
    assert set(by_title) == {"IA2.14 normalization", "Experiment 8"}  # Materials create no task.
    ia = by_title["IA2.14 normalization"]
    assert (
        ia.due_at == datetime(2026, 10, 1, 18, 29, tzinfo=UTC) and ia.completed_at
    )  # TURNED_IN after deadline still completes.
    assert ia.data["completion"]["origin"] == "classroom_turned_in"
    assert by_title["Experiment 8"].completed_at is None
    assert [r["issueType"] for r in reviews(client, headers)] == ["returned_ambiguous"]
    # A genuinely newer explicit unsubmission reopens the same task.
    fake.submissions["c1"][0] = {**fake.submissions["c1"][0], "state": "RECLAIMED_BY_STUDENT", "updateTime": later,
        "submissionHistory": [{"stateHistory": {"state": "TURNED_IN", "stateTimestamp": recent}},
                              {"stateHistory": {"state": "RECLAIMED_BY_STUDENT", "stateTimestamp": later}}]}  # fmt: skip
    run(client, headers, conn)
    ia = next(t for t in tasks(student.uid) if t.title == "IA2.14 normalization")
    assert ia.completed_at is None and effective_status(ia, now()) == "missed"
    assert len(tasks(student.uid)) == 2


def test_merge_undo_kind_guard_and_evidence_reassignment(client, headers, student, fake, auto):
    subjects = setup_student(client, headers)
    send(
        fake,
        "d",
        LMS,
        reminder("EXP10", "Monday, 26 October 2026 11:59 PM IST", 95000),
        now() - timedelta(days=2),
    )
    send(fake, "r", LMS, receipt("EXP10", "DS_B_ODD_26-27", 95000, "x"), now() - timedelta(days=1), [AUTH])
    conn = connect(client, headers, fake)
    run(client, headers, conn)
    (imported,) = tasks(student.uid)
    assert imported.completed_at and str(imported.subject_id) == subjects["Data Structures Laboratory"]["id"]
    manual = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "EXP10 write-up",
            "type": "assignment",
            "subjectId": subjects["Data Structures Laboratory"]["id"],
        },
    ).json()
    theory = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "EXP10", "type": "assignment", "subjectId": subjects["Data Structures"]["id"]},
    ).json()
    imp = client.get(f"/api/v1/tasks/{imported.id}", headers=headers).json()
    bad = client.post(
        "/api/v1/task-merges",
        headers=fresh(headers),
        json={
            "survivingTaskId": imp["id"],
            "absorbedTaskId": theory["id"],
            "survivingRevision": imp["revision"],
            "absorbedRevision": theory["revision"],
        },
    )
    assert bad.status_code == 422  # Different theory/lab subjects never merge.
    merge = client.post(
        "/api/v1/task-merges",
        headers=fresh(headers),
        json={
            "survivingTaskId": manual["id"],
            "absorbedTaskId": imp["id"],
            "survivingRevision": manual["revision"],
            "absorbedRevision": imp["revision"],
        },
    )
    assert merge.status_code == 201, merge.text
    survivor = client.get(f"/api/v1/tasks/{manual['id']}", headers=headers).json()
    assert survivor["status"] == "completed" and survivor["source"] == "gmail"
    listed = client.get("/api/v1/tasks?q=EXP10", headers=headers).json()["items"]
    assert imp["id"] not in {t["id"] for t in listed}
    assert (
        client.post(f"/api/v1/task-merges/{merge.json()['id']}/undo", headers=fresh(headers)).status_code
        == 200
    )
    assert client.get(f"/api/v1/tasks/{manual['id']}", headers=headers).json()["status"] == "due"
    assert client.get(f"/api/v1/tasks/{imp['id']}", headers=headers).json()["mergedInto"] is None
    # Reassigning the receipt moves completion with its evidence.
    receipt_ev = next(
        e
        for e in client.get(f"/api/v1/tasks/{imp['id']}/evidence", headers=headers).json()["items"]
        if e["eventType"] == "submission" and e["state"] == "active"
    )
    moved = client.post(
        f"/api/v1/evidence/{receipt_ev['id']}/reassign", headers=fresh(headers), json={"taskId": manual["id"]}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["fromTask"]["status"] == "due" and moved.json()["toTask"]["status"] == "completed"


def test_rules_validation_order_and_natural_language_preview(client, headers, monkeypatch):
    setup_student(client, headers)
    bad = {
        "name": "Code",
        "conditions": [{"field": "sql", "value": "drop table"}],
        "action": {"type": "exclude"},
    }
    assert client.post("/api/v1/rules", headers=headers, json=bad).status_code == 422
    other = {
        "name": "Foreign",
        "conditions": [{"field": "subjectId", "value": "00000000-0000-0000-0000-000000000000"}],
        "action": {"type": "exclude"},
    }
    assert client.post("/api/v1/rules", headers=headers, json=other).status_code == 422
    a = client.post(
        "/api/v1/rules",
        headers=headers,
        json={
            "name": "A",
            "conditions": [{"field": "taskType", "value": "test"}],
            "action": {"type": "priority", "priority": "critical"},
        },
    ).json()
    b = client.post(
        "/api/v1/rules",
        headers=headers,
        json={
            "name": "B",
            "conditions": [{"field": "keyword", "value": "hackathon"}],
            "action": {"type": "exclude"},
        },
    ).json()
    ordered = client.put("/api/v1/rules/order", headers=headers, json={"ids": [b["id"], a["id"]]}).json()[
        "items"
    ]
    assert [r["name"] for r in ordered] == ["B", "A"]
    assert client.put("/api/v1/rules/order", headers=headers, json={"ids": [a["id"]]}).status_code == 409
    assert (
        client.post(
            "/api/v1/rules/interpret", headers=headers, json={"instruction": "ignore hackathons"}
        ).status_code
        == 503
    )

    def preview(instruction, subjects):
        return ai.RulePreview.model_validate({"name": "No hackathons", "conditions": [{"field": "keyword", "value": "hackathon"}],
                                              "action": {"type": "exclude"}, "unsupported": "Cannot delete emails"}), {"provider": "fake"}  # fmt: skip

    monkeypatch.setattr(ai, "interpret_rule", preview)
    out = client.post(
        "/api/v1/rules/interpret", headers=headers, json={"instruction": "ignore hackathons and delete them"}
    ).json()
    assert out["rule"]["action"] == {"type": "exclude", "priority": None} and out["unsupported"]
    assert len(client.get("/api/v1/rules", headers=headers).json()["items"]) == 2  # Preview is not saved.


def test_review_cross_user_isolation_and_suppression(client, headers, student, fake, model):
    from tests.conftest import account

    subjects = setup_student(client, headers)
    model.items = {"WDL practical ESE window": [{
        "intent": "new_work", "taskType": "test", "title": "WDL practical ESE",
        "subjectId": subjects["Web Development Laboratory"]["id"], "targeting": {"classYears": ["SY"], "allBatches": True},
        "timing": {"dateWindowStart": "2026-11-30", "dateWindowEnd": "2026-12-04"}}]}  # fmt: skip
    send(
        fake,
        "d",
        LMS,
        ("WDL practical ESE window", "Practical exam between 30 Nov and 4 Dec"),
        now() - timedelta(days=1),
    )
    conn = connect(client, headers, fake)
    run(client, headers, conn)
    (item,) = reviews(client, headers)
    other = account()
    assert client.get("/api/v1/review-items", headers=other.headers).json()["items"] == []
    r = client.post(
        f"/api/v1/review-items/{item['id']}/resolve",
        headers=other.headers,
        json={"revision": 1, "action": "dismiss"},
    )
    assert r.status_code == 404
    client.put("/api/v1/sender-preferences/" + quote(LMS), headers=headers, json={"action": "block"})
    assert reviews(client, headers) == [] and len(reviews(client, headers, "suppressed")) == 1


@pytest.mark.skipif(not REFERENCE.exists(), reason="reference archive not present")
def test_reference_lms_exports_reconcile_without_duplicates(
    client, headers, student, fake, auto, monkeypatch
):
    subjects = setup_student(client, headers)
    # The reference account's address is the recipient of these exports.
    for i, f in enumerate(sorted(REFERENCE.glob("*.eml"))):
        fake.add_message(f"ref{i}", f.read_bytes(), ts=now() - timedelta(days=1, minutes=i))
    fake.service = "gmail"
    conn = connect(client, headers, fake, email="dhruv.kumar@somaiya.edu")
    run(client, headers, conn, limit=200)
    for item in reviews(client, headers):
        if item["issueType"] == "choose_subject":
            choice = (
                subjects["Data Structures Laboratory"]["id"]
                if "Data Structures" in (item["courseLabel"] or "")
                else item["subjectChoices"][0]
            )
            resolve(client, headers, item, action="accept", subjectId=choice, rememberAlias=True)
    r = client.post(f"/api/v1/connections/{conn}/reprocess", headers=fresh(headers))
    job = r.json()["job"]
    while job["status"] not in ("completed", "failed"):
        job = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers).json()
    by_title = {}
    for t in tasks(student.uid):
        by_title.setdefault(t.title.upper(), []).append(t)
    assert all(len(v) == 1 for v in by_title.values()), by_title.keys()  # No duplicate tasks.
    exp6 = by_title["EXP6-BST"][0]
    assert exp6.completed_at and exp6.due_at == ist(2026, 9, 21, 23, 59)
    itvc = by_title["IA-2 : AI-ENHANCED MODELING"][0]
    assert itvc.completed_at and itvc.due_at == ist(2026, 10, 9, 23, 59)
    assert not by_title["EXP 5- DOUBLY LL, CIRCULAR LL"][0].completed_at


def test_groq_primary_repair_then_fallback_model(monkeypatch):
    import json as _json

    import httpx

    monkeypatch.setattr(settings(), "groq_api_key", "test-key")
    monkeypatch.setattr(settings(), "groq_model", "primary-model")
    monkeypatch.setattr(settings(), "groq_fallback_model", "fallback-model")
    calls = []

    def post(url, headers, json, timeout):
        calls.append((url, json["model"]))
        assert (
            json["response_format"] == {"type": "json_object"}
            and headers["authorization"] == "Bearer test-key"
        )
        if json["model"] == "primary-model":
            return httpx.Response(503, request=httpx.Request("POST", url))
        content = "not json" if len(calls) == 2 else _json.dumps({"items": [{"intent": "unknown"}]})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", post)
    out, meta = ai.structured("Return JSON", "{}", ai.Extraction)
    assert out.items[0].intent == "unknown"
    assert meta == {"provider": "groq", "model": "fallback-model", "repaired": True}
    assert [m for _, m in calls] == ["primary-model", "fallback-model", "fallback-model"]
    assert all(u == "https://api.groq.com/openai/v1/chat/completions" for u, _ in calls)
    monkeypatch.setattr(settings(), "groq_api_key", "")
    with pytest.raises(ai.AIUnavailable):
        ai.structured("Return JSON", "{}", ai.Extraction)


def test_lms_sender_and_host_are_always_recognized(monkeypatch):
    monkeypatch.setattr(settings(), "lms_senders", "")
    monkeypatch.setattr(settings(), "lms_hosts", "")
    assert "lms-kjsse@somaiya.edu" in interpret.lms_senders()
    assert "lms-kjsce.somaiya.edu" in interpret.lms_hosts()


def reprocess(client, headers, conn):
    job = client.post(f"/api/v1/connections/{conn}/reprocess", headers=fresh(headers)).json()["job"]
    while job["status"] not in ("completed", "failed"):
        job = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers).json()


def test_kt_notices_follow_the_student_setting(client, headers, student, fake, model):
    subjects = setup_student(client, headers)
    ds = subjects["Data Structures"]["id"]
    me = client.get("/api/v1/me", headers=headers).json()
    assert me["ignoreKtNotices"] is False  # Default: KT notices are processed like any other.
    r = client.patch(
        "/api/v1/me", headers=fresh(headers), json={"revision": me["revision"], "ignoreKtNotices": True}
    )
    assert r.status_code == 200 and r.json()["ignoreKtNotices"] is True
    exam = {"divisions": ["B"]}
    model.items = {
        # Flagged by the extraction.
        "DS exam schedule for November": [{"intent": "new_work", "taskType": "test", "title": "DS end-semester exam",
            "subjectId": ds, "ktOnly": True, "targeting": exam, "timing": {"startsAt": "2026-11-20T10:00:00+05:30"}}],
        # Missed by the extraction but plainly worded.
        "ATKT examination form": [{"intent": "new_work", "taskType": "assignment", "title": "Submit exam form",
            "subjectId": ds, "targeting": exam, "timing": {"dueAt": "2026-11-01T17:00:00+05:30"}}],
        # Regular and KT students together is not KT-only.
        "Regular and KT students: DS IA2": [{"intent": "new_work", "taskType": "test", "title": "DS IA2",
            "subjectId": ds, "targeting": exam, "timing": {"startsAt": "2026-10-20T10:00:00+05:30"}}],
        "KT exam timetable": [{"intent": "new_work", "taskType": "test", "title": "KT exam DS", "subjectId": ds,
            "ktOnly": True, "timing": {"startsAt": "2026-11-25T10:00:00+05:30"}}],
    }  # fmt: skip
    t0 = now() - timedelta(days=3)
    for gid, subject in [
        ("k1", "DS exam schedule for November"),
        ("k2", "ATKT examination form"),
        ("k3", "Regular and KT students: DS IA2"),
    ]:
        send(fake, gid, "exam.cell@somaiya.edu", (subject, f"{subject}. Details of the exam inside."), t0)
    conn = connect(client, headers, fake, "gmail")
    run(client, headers, conn)
    assert [t.title for t in tasks(student.uid)] == ["DS IA2"]
    stamp = t0.isoformat().replace("+00:00", "Z")
    fake.courses = [{"id": "c1", "name": "DS Div B"}]
    fake.coursework["c1"] = [{"id": "w1", "title": "KT exam timetable", "description": "KT exam on 25 Nov",
        "workType": "MATERIAL", "creationTime": stamp, "updateTime": stamp}]  # fmt: skip
    room = connect(client, headers, fake, "classroom", code="c2")
    run(client, headers, room)  # Discovers the course so it can be linked.
    client.put(f"/api/v1/subjects/{ds}/classroom-mappings/{room}/c1", headers=fresh(headers))
    run(client, headers, room)
    assert [t.title for t in tasks(student.uid)] == ["DS IA2"]
    with transaction(student.uid) as db:
        outcomes = db.scalars(select(SourceEvent.outcome).where(SourceEvent.user_id == student.uid)).all()
    assert sorted(outcomes).count("ignored_kt") == 3
    # Turning the setting off and reprocessing brings earlier KT notices back.
    me = client.get("/api/v1/me", headers=headers).json()
    client.patch(
        "/api/v1/me", headers=fresh(headers), json={"revision": me["revision"], "ignoreKtNotices": False}
    )
    reprocess(client, headers, conn)
    reprocess(client, headers, room)
    assert sorted(t.title for t in tasks(student.uid)) == [
        "DS IA2",
        "DS end-semester exam",
        "KT exam DS",
        "Submit exam form",
    ]


def test_subjects_are_linked_automatically_without_asking(client, headers, student, fake, model, monkeypatch):
    from duecare import subject_link

    subjects = setup_student(client, headers)
    ds, dsl = subjects["Data Structures"]["id"], subjects["Data Structures Laboratory"]["id"]
    itvc = subjects["Integral Transforms and Vector Calculus"]["id"]
    seen = []

    def linker(system, user, schema, deadline=None):
        import json as _json

        payload = _json.loads(user)
        seen.append(payload)
        if system == subject_link.COURSE_SYSTEM:
            return schema.model_validate(
                {
                    "links": [
                        {"key": c["key"], "subjectIds": [itvc] if "Maths" in c["name"] else []}
                        for c in payload["courses"]
                    ]
                }  # fmt: skip
            ), {"provider": "fake", "model": "link-1"}
        picks = {"Laplace worksheet": itvc, "Club quiz": "not-a-subject"}
        return schema.model_validate(
            {"links": [{"key": i["key"], "subjectId": picks.get(i["title"])} for i in payload["items"]]}
        ), {"provider": "fake", "model": "link-1"}

    monkeypatch.setattr(ai, "providers", lambda: [("fake", "link-1", None)])
    monkeypatch.setattr(ai, "structured", linker)
    item = {"intent": "new_work", "taskType": "assignment", "targeting": {"divisions": ["B"]},
            "timing": {"dueAt": "2026-11-02T23:59:00+05:30"}}  # fmt: skip
    model.items = {
        "DS assignment 3": [{**item, "title": "DS assignment 3"}],  # Short form settles it: theory.
        "DS journal": [
            {**item, "title": "DS journal write-up", "targeting": {"batches": ["B2"]}}
        ],  # The DS lab.
        "Laplace worksheet": [{**item, "title": "Laplace worksheet"}],  # Only AI can tell.
        "Club quiz": [{**item, "title": "Club quiz"}],  # Invented ID: kept without a subject.
    }
    t0 = now() - timedelta(days=1)
    for gid, subject in [("s1", "DS assignment 3"), ("s2", "DS journal"), ("s3", "Laplace worksheet"),
                         ("s4", "Club quiz")]:  # fmt: skip
        send(fake, gid, "faculty.x@somaiya.edu", (subject, subject + " assignment due 2 Nov"), t0)
    conn = connect(client, headers, fake)
    run(client, headers, conn)
    assert reviews(client, headers) == []  # Never "Which of your subjects is this for?".
    linked = {t.title: (str(t.subject_id) if t.subject_id else None, t.data["subjectLink"]["method"])
              for t in tasks(student.uid)}  # fmt: skip
    assert linked == {
        "DS assignment 3": (ds, "name"),
        "DS journal write-up": (dsl, "name"),
        "Laplace worksheet": (itvc, "ai"),
        "Club quiz": (None, "none"),
    }
    # The AI only ever sees work the names could not settle.
    assert {i["title"] for p in seen if "items" in p for i in p["items"]} == {
        "Laplace worksheet",
        "Club quiz",
    }

    # When only linking needs the AI and it is unavailable, the work is kept without a subject.
    def down(*args, **kwargs):
        raise ai.AIUnavailable("AI providers are temporarily unavailable")

    monkeypatch.setattr(ai, "structured", down)
    model.items["Fourier worksheet"] = [{**item, "title": "Fourier worksheet"}]
    send(fake, "s5", "faculty.x@somaiya.edu", ("Fourier worksheet", "Worksheet assignment due 2 Nov"), now())
    job = run(client, headers, conn)
    assert not job["progress"].get("aiPaused") and reviews(client, headers) == []
    fourier = next(t for t in tasks(student.uid) if t.title == "Fourier worksheet")
    assert fourier.subject_id is None and fourier.data["subjectLink"]["reason"] == "ai_unavailable"

    # Classroom courses link themselves by name or, failing that, by AI.
    monkeypatch.setattr(ai, "structured", linker)
    fake.courses = [
        {"id": "k1", "name": "DS Div B 2026", "courseState": "ACTIVE"},
        {"id": "k2", "name": "Maths III (Prof. R)", "courseState": "ACTIVE"},
        {"id": "k3", "name": "Coding club", "courseState": "ACTIVE"},
    ]
    room = connect(client, headers, fake, "classroom", code="c2")
    run(client, headers, room)
    courses = client.get(f"/api/v1/connections/{room}/classroom-courses", headers=headers).json()["items"]
    links = {c["externalCourseId"]: sorted(m["subjectId"] for m in c["mappings"]) for c in courses}
    assert links == {"k1": sorted([ds, dsl]), "k2": [itvc], "k3": []}


def test_earlier_subject_questions_are_settled_on_the_next_sync(client, headers, student, fake):
    from duecare.models import TaskEvidence

    subjects = setup_student(client, headers)
    send(
        fake,
        "q1",
        LMS,
        reminder("EXP12", "Monday, 26 October 2026 11:59 PM IST", 97000),
        now() - timedelta(days=1),
    )
    conn = connect(client, headers, fake)
    run(client, headers, conn)
    # Recreate the state left by the old flow: no task, an open "Which subject?" question.
    with transaction(student.uid) as db:
        (event,) = db.scalars(select(SourceEvent).where(SourceEvent.user_id == student.uid))
        identity, record_id = event.identity_key, event.source_record_id
        db.execute(delete(TaskEvidence).where(TaskEvidence.user_id == student.uid))
        db.execute(delete(SourceEvent).where(SourceEvent.user_id == student.uid))
        db.execute(delete(Task).where(Task.user_id == student.uid))
        db.get(interpret.SourceRecord, record_id).processing_state = "needs_review"
        db.add(ReviewItem(user_id=student.uid, issue_type="choose_subject", status="open", source_record_id=record_id,
                          question="Which of your subjects is this for?", data={"identityKey": identity}))  # fmt: skip
        db.commit()
    assert [r["issueType"] for r in reviews(client, headers)] == ["choose_subject"]
    run(client, headers, conn)
    (task,) = tasks(student.uid)
    assert str(task.subject_id) == subjects["Data Structures Laboratory"]["id"]
    assert reviews(client, headers) == []


def test_full_course_names_link_to_subjects_named_by_short_forms():
    from duecare import subject_link

    subjects = [{"id": f"{n}|{k}", "name": n, "kind": k} for n, k in [
        ("DS", "theory"), ("DS", "lab"), ("ITVC", "theory"), ("ITVC", "tutorial"), ("COA", "theory"),
        ("DBMS", "theory"), ("DBMS", "lab"), ("DSM", "theory"), ("WDL", "lab")]]  # fmt: skip
    cases = {
        ("Data Structures_B_ODD_26-27", "EXP6-BST"): "DS|lab",
        ("Data Structures_B_ODD_26-27", "DS IA1 (MCQ Quiz)"): "DS|theory",
        ("Integral Transforms and Vector Calculus_A-B-C-D_SY_ODD_26-27", "Tutorial 3:Laplace transform(QUIZ)"): "ITVC|tutorial",
        ("Integral Transforms and Vector Calculus_A-B-C-D_SY_ODD_26-27", "IA -1_5th September 2026 8 pm"): "ITVC|theory",
        ("Computer Organization & Architecture_B_ODD_26-27", "COA Quiz - IA-1 ODD 2026-27"): "COA|theory",
        ("Relational Database Management Systems_B_ODD_26-27", "DBMS_IA1_Quiz"): "DBMS|theory",
        ("Applied Mathematics – II_2025-26", "IA (module 1,2,3) for KT"): None,
    }  # fmt: skip
    for texts, expected in cases.items():
        component = subject_link.component_of(" ".join(texts))
        assert subject_link.deterministic(list(texts), subjects, component) == expected, texts


def test_streaming_ai_creates_task_before_gmail_import_finishes(
    client, headers, student, fake, model, monkeypatch
):
    subjects = setup_student(client, headers)
    title = "COA streaming assignment"
    model.items[title] = [
        {
            "intent": "new_work",
            "taskType": "assignment",
            "title": title,
            "subjectId": subjects["Computer Organization & Architecture"]["id"],
            "targeting": {"divisions": ["B"]},
            "timing": {"dueAt": "2026-11-02T23:59:00+05:30"},
        }
    ]
    send(fake, "first", "faculty@somaiya.edu", (title, "Assignment due 2 Nov"), now())
    send(
        fake, "second", "faculty@somaiya.edu", ("Other notice", "Announcement"), now() - timedelta(minutes=1)
    )
    conn = connect(client, headers, fake)
    blocked, release = Event(), Event()
    metadata = fake.gmail_metadata

    def hold_second(token, gid):
        if gid == "second":
            blocked.set()
            assert release.wait(15), "test did not release importer"
        return metadata(token, gid)

    monkeypatch.setattr(fake, "gmail_metadata", hold_second)
    monkeypatch.setattr(settings(), "sync_work_budget_seconds", 30)
    job = client.post(f"/api/v1/connections/{conn}/sync", headers=fresh(headers), json={}).json()["job"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers)
        try:
            assert blocked.wait(10)
            timeout = time.monotonic() + 10
            found = []
            while time.monotonic() < timeout:
                found = tasks(student.uid)
                if found:
                    break
                time.sleep(0.05)
            assert [t.title for t in found] == [title]
            assert found[0].due_at == ist(2026, 11, 2, 23, 59)
            assert title in model.calls and not future.done()
            partial = client.get(f"/api/v1/sync-jobs/{job['id']}", headers=headers).json()
            assert partial["status"] == "running" and partial["progress"]["tasksCreated"] == 1
        finally:
            release.set()
        response = future.result(timeout=15)
    assert response.status_code == 200 and response.json()["status"] == "completed"
    assert len(tasks(student.uid)) == 1


def test_streaming_cancellation_discards_in_flight_interpretation(
    client, headers, student, fake, model, monkeypatch
):
    setup_student(client, headers)
    send(fake, "one", "faculty@somaiya.edu", ("COA assignment", "Assignment due tomorrow"), now())
    conn = connect(client, headers, fake)
    started, release = Event(), Event()
    original = interpret.prepare

    def held(*args, **kwargs):
        result = original(*args, **kwargs)
        started.set()
        assert release.wait(15)
        return result

    monkeypatch.setattr(interpret, "prepare", held)
    monkeypatch.setattr(settings(), "sync_work_budget_seconds", 30)
    job = client.post(f"/api/v1/connections/{conn}/sync", headers=fresh(headers), json={}).json()["job"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers)
        try:
            assert started.wait(10)
            with transaction(student.uid) as db:
                sync.cancel_jobs(db, conn, "test_cancel")
                assert "messageFingerprints" not in db.get(sync.SyncJob, job["id"]).checkpoint
                db.commit()
        finally:
            release.set()
        response = future.result(timeout=15)
    assert response.json()["status"] == "cancelled"
    assert records(student.uid)[0].processing_state == "awaiting_interpretation"
    assert tasks(student.uid) == []


def test_ai_rate_limit_cools_down_without_repeated_provider_calls(monkeypatch):
    import httpx

    monkeypatch.setattr(settings(), "groq_api_key", "test-only")
    monkeypatch.setattr(settings(), "groq_model", "rate-limit-fixture")
    monkeypatch.setattr(settings(), "groq_fallback_model", "")
    calls = []

    def limited(url, **kwargs):
        calls.append(url)
        return httpx.Response(429, headers={"retry-after": "120"})

    monkeypatch.setattr(ai.httpx, "post", limited)
    with pytest.raises(ai.AIUnavailable):
        ai.structured("synthetic", "synthetic", ai.Extraction)
    with pytest.raises(ai.AIUnavailable):
        ai.structured("synthetic", "synthetic", ai.Extraction)
    assert len(calls) == 1
    monkeypatch.setitem(ai._cooldowns, ("groq", "rate-limit-fixture"), time.monotonic() - 1)
    with pytest.raises(ai.AIUnavailable):
        ai.structured("synthetic", "synthetic", ai.Extraction)
    assert len(calls) == 2


def test_streaming_receipt_waits_for_older_assignment(client, headers, student, fake, auto):
    setup_student(client, headers)
    send(
        fake,
        "receipt-first",
        LMS,
        receipt("EXP6-BST", "DS_B_ODD_26-27", 91919, "exp6.docx"),
        now() - timedelta(hours=1),
        [AUTH],
    )
    send(
        fake,
        "notice-later",
        LMS,
        reminder("EXP6-BST", "Monday, 21 September 2026 11:59 PM IST", 91919),
        now() - timedelta(hours=2),
    )
    conn = connect(client, headers, fake)
    job = run(client, headers, conn)
    assert job["status"] == "completed"
    (task,) = tasks(student.uid)
    assert task.title == "EXP6-BST" and task.completed_at
    assert task.due_at == ist(2026, 9, 21, 23, 59)


def test_streaming_budget_expiry_stays_queued_without_ai_pause(
    client, headers, student, fake, model, monkeypatch
):
    setup_student(client, headers)
    send(fake, "one", "faculty@somaiya.edu", ("COA assignment", "Assignment due tomorrow"), now())
    conn = connect(client, headers, fake)

    def exhausted(payload):
        raise ai.BudgetExpired("AI interpretation ran out of time")

    monkeypatch.setattr(ai, "extract", exhausted)
    job = client.post(f"/api/v1/connections/{conn}/sync", headers=fresh(headers), json={}).json()["job"]
    result = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers).json()
    assert result["status"] == "queued"
    (record,) = records(student.uid)
    assert record.processing_state == "awaiting_interpretation" and "aiPausedUntil" not in record.data
    monkeypatch.setattr(ai, "extract", model)
    assert run(client, headers, conn)["status"] == "completed"


def test_assignment_receipt_completes_by_default_and_reminders_cannot_reopen(client, headers, student, fake):
    setup_student(client, headers)
    title = "EXP5 Queue exercise"
    send(
        fake,
        "notice",
        LMS,
        reminder(title, "Monday, 28 September 2026 11:59 PM IST", 90242),
        now() - timedelta(days=3),
    )
    conn = connect(client, headers, fake)
    run(client, headers, conn)
    body = (
        f"DS_B_ODD_26-27 -> Assignment -> {title}\n"
        f"Your assignment submission for '{title}' has been submitted.\n"
        f"You can view your submission and check its status on the assignment page.\n"
        f"{HOST}/mod/assign/view.php?id=90242\n"
    )
    send(
        fake,
        "receipt",
        LMS,
        (f"Assignment submission confirmation - {title}", body),
        now() - timedelta(days=2),
        [AUTH],
    )
    run(client, headers, conn)
    (task,) = tasks(student.uid)
    assert task.completed_at and task.data["completion"]["origin"] == "lms_assignment_receipt"
    send(
        fake,
        "overdue",
        LMS,
        overdue(title, "DS_B_ODD_26-27", "MONDAY, 28 SEPTEMBER 2026, 11:59 PM", 90242),
        now(),
    )
    run(client, headers, conn)
    assert tasks(student.uid)[0].completed_at
    assert client.get(f"/api/v1/tasks/{task.id}", headers=headers).json()["status"] == "completed"
    assert reviews(client, headers) == []


@pytest.mark.parametrize("automatic", [False, True])
def test_quiz_submission_receipt_completes_test_and_stays_completed(
    client, headers, student, fake, automatic
):
    setup_student(client, headers)
    title = "DS IA1 quiz"
    notice = (
        f"Opens on Thursday, 1 October 2026, 8:00 PM: {title}",
        f"The quiz {title} in course DataStructures_B_SY_ODD_26-27 is opening soon. "
        f"OPENS: THURSDAY, 1 OCTOBER 2026, 8:00 PM\n"
        f"CLOSES: THURSDAY, 1 OCTOBER 2026, 9:00 PM\nGo to quiz {HOST}/mod/quiz/view.php?id=99123",
    )
    send(fake, "quiz", LMS, notice, now() - timedelta(days=3))
    conn = connect(client, headers, fake)
    run(client, headers, conn)
    (task,) = tasks(student.uid)
    assert task.type == "test" and effective_status(task, now()) == "missed"
    statement = (
        f"The time for the quiz '{title}' in the course 'DataStructures_B_SY_ODD_26-27' expired. "
        "Your answers were submitted automatically at 9 PM."
        if automatic
        else f"Thank you for submitting your answers to '{title}' in course 'DataStructures_B_SY_ODD_26-27' at 8:45 PM."
    )
    confirmation = (
        f"Hi STUDENT,\n{statement}\nThis message confirms that your answers have been saved.\n"
        f"You can access this quiz at {HOST}/mod/quiz/view.php?id=99123."
    )
    send(
        fake,
        "quiz-receipt",
        LMS,
        (f"Submission confirmation: {title}", confirmation),
        now() - timedelta(days=1),
        [AUTH],
    )
    run(client, headers, conn)
    (task,) = tasks(student.uid)
    assert task.completed_at and task.data["completion"]["origin"] == "lms_quiz_receipt"
    send(
        fake,
        "quiz-closing",
        LMS,
        reminder(
            title,
            "Thursday, 1 October 2026 9:00 PM IST",
            99123,
            kind="Quiz",
            course="DataStructures_B_SY_ODD_26-27",
        ),
        now(),
    )
    run(client, headers, conn)
    assert client.get(f"/api/v1/tasks/{task.id}", headers=headers).json()["status"] == "completed"


def test_receipt_is_retried_when_its_task_arrives_on_a_later_sync(client, headers, student, fake):
    setup_student(client, headers)
    send(
        fake,
        "early-receipt",
        LMS,
        receipt("EXP5 Queue", "DS_B_ODD_26-27", 90242, "report.docx"),
        now() - timedelta(days=1),
        [AUTH],
    )
    conn = connect(client, headers, fake)
    run(client, headers, conn)
    assert tasks(student.uid) == []
    assert records(student.uid)[0].reason == "unmatched_receipt"
    send(
        fake,
        "late-notice",
        LMS,
        reminder("EXP5 Queue", "Monday, 28 September 2026 11:59 PM IST", 90242),
        now() - timedelta(days=2),
    )
    job = run(client, headers, conn)
    assert job["status"] == "completed"
    (task,) = tasks(student.uid)
    assert task.completed_at
    assert reviews(client, headers) == []
    source = next(r for r in records(student.uid) if r.provider_id.endswith(":early-receipt"))
    assert source.processing_state == "interpreted" and source.data["receiptRetry"] == 1


def test_gmail_queue_is_newest_first_and_excludes_mail_older_than_30_days(client, headers, student, fake):
    from duecare.models import SourceRecord

    conn = connect(client, headers, fake)
    ids = {}
    with transaction(student.uid) as db:
        for name, age in [("old", 31), ("recent", 5), ("newest", 1)]:
            r = SourceRecord(
                user_id=student.uid,
                connection_id=conn,
                provider_id=f"gmail:fixture:{name}",
                kind="gmail_message",
                processing_state="awaiting_interpretation",
                processing_version="fixture",
                received_at=now() - timedelta(days=age),
                data={"aiPausedReason": "fixture"} if age == 31 else {},
            )
            db.add(r)
            db.flush()
            ids[name] = r.id
        db.commit()
    assert interpret.next_record(student.uid, conn) == ids["newest"]
    counts = client.get("/api/v1/connections", headers=headers).json()["items"][0]["records"]
    assert counts["awaitingInterpretation"] == 2 and counts["aiPaused"] == 0


def test_stated_dates_survive_side_questions_and_missing_offsets(client, headers, student, fake, model):
    ds = setup_student(client, headers)["Data Structures"]["id"]
    div = {"divisions": ["B"]}
    model.items = {
        # A question about something other than timing must not discard a stated time, and a
        # time without an offset is India time rather than no time at all.
        "DS IA2 quiz on 20 Oct at 1:30 pm": [{"intent": "new_work", "taskType": "test", "title": "DS IA2 quiz", "subjectId": ds,
            "targeting": div, "timing": {"startsAt": "2026-10-20T13:30:00"}, "question": "Is a calculator allowed?", "evidence": "DS IA2 quiz on 20 Oct"}],
        # A bare date in a precise field is a date-only deadline.
        "DS assignment 3 due on 22 Oct": [{"intent": "new_work", "taskType": "assignment", "title": "DS assignment 3",
            "subjectId": ds, "targeting": div, "timing": {"dueAt": "2026-10-22"}, "evidence": "DS assignment 3 due on 22 Oct"}],
        # A real doubt about timing keeps the date, widened to the days it names, as tentative.
        "DS lab test date tentative": [{"intent": "new_work", "taskType": "test", "title": "DS lab test", "subjectId": ds,
            "targeting": div, "timing": {"startsAt": "2026-10-25T10:00:00+05:30"},
            "question": "Which date applies, 25 or 26 October?", "evidence": "DS lab test date tentative"}],
    }  # fmt: skip
    t0 = now() - timedelta(days=2)
    for gid, subject in [
        ("q1", "DS IA2 quiz on 20 Oct at 1:30 pm"),
        ("q2", "DS assignment 3 due on 22 Oct"),
        ("q3", "DS lab test date tentative"),
    ]:
        send(
            fake,
            gid,
            "faculty.ds@somaiya.edu",
            (subject, f"{subject}. Division B, submit the assignment."),
            t0,
        )
    conn = connect(client, headers, fake, "gmail")
    run(client, headers, conn)
    by_title = {t.title: t for t in tasks(student.uid)}
    assert by_title["DS IA2 quiz"].due_at == datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    assert by_title["DS assignment 3"].due_at == datetime(2026, 10, 22, 18, 29, tzinfo=UTC)
    assert by_title["DS assignment 3"].data["dueDate"] == "2026-10-22"
    lab = by_title["DS lab test"]
    assert lab.data["dateWindowStart"] == "2026-10-25" and lab.due_at == datetime(
        2026, 10, 26, 18, 29, tzinfo=UTC
    )
    assert lab.data["timingTentative"]["question"].startswith("Which date applies")


def test_classroom_due_dates_fill_tests_and_bare_coursework(client, headers, student, fake, model):
    setup_student(client, headers)
    dbms = client.post("/api/v1/subjects", headers=headers, json={"name": "DBMS", "kind": "theory"}).json()
    recent = (now() - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    base = {"creationTime": recent, "updateTime": recent}
    fake.courses = [{"id": "c1", "name": "26-27 dbms Div B"}]
    fake.coursework["c1"] = [
        # Midnight UTC arrives as an empty dueTime.
        {**base, "id": "w1", "title": "DBMS IA1 quiz", "description": "Online quiz", "workType": "ASSIGNMENT",
         "dueDate": {"year": 2026, "month": 10, "day": 15}, "dueTime": {}},
        {**base, "id": "w2", "title": "Experiment 9", "description": "", "workType": "ASSIGNMENT",
         "dueDate": {"year": 2026, "month": 10, "day": 18}, "dueTime": {"hours": 18, "minutes": 29}},
        {**base, "id": "w3", "title": "Reading list", "description": "Optional reading", "workType": "ASSIGNMENT"},
        {**base, "id": "w4", "title": "Lab manual", "description": "", "workType": "MATERIAL"},
    ]  # fmt: skip
    model.items = {
        # The model names a test but gives no time: Classroom's own due date fills it in.
        "DBMS IA1 quiz": [{"intent": "new_work", "taskType": "test", "title": "DBMS IA1 quiz", "subjectId": dbms["id"], "evidence": "DBMS IA1 quiz"}],
        "Experiment 9": [],  # Nothing extracted from a bare title: the coursework is still kept.
        "Reading list": [{"intent": "supporting", "title": "Reading list"}],
        "Lab manual": [],
    }  # fmt: skip
    conn = connect(client, headers, fake, "classroom")
    run(client, headers, conn)
    client.put(f"/api/v1/subjects/{dbms['id']}/classroom-mappings/{conn}/c1", headers=fresh(headers))
    run(client, headers, conn)
    by_title = {t.title: t for t in tasks(student.uid)}
    assert set(by_title) == {"DBMS IA1 quiz", "Experiment 9"}
    quiz = by_title["DBMS IA1 quiz"]
    assert quiz.due_at == datetime(2026, 10, 15, 0, 0, tzinfo=UTC) and quiz.type == "test"
    exp = by_title["Experiment 9"]
    assert exp.due_at == datetime(2026, 10, 18, 18, 29, tzinfo=UTC) and exp.type == "assignment"
    assert str(exp.subject_id) == dbms["id"]


def test_stated_dates_survive_model_timing_mistakes(client, headers, student, fake, model):
    subjects = setup_student(client, headers)
    coa, wdl = (
        subjects["Computer Organization & Architecture"]["id"],
        subjects["Web Development Laboratory"]["id"],
    )
    ds = subjects["Data Structures"]["id"]
    div = {"divisions": ["B"]}
    same = "2026-09-28T13:30:00+05:30"
    model.items = {
        # One time copied into every role must not make the whole schedule invalid.
        "COA IA 1 scheduled on 28/09/2026 at 1:30 pm": [{"intent": "new_work", "taskType": "test",
            "title": "COA IA 1", "subjectId": coa, "targeting": div, "evidence": "COA IA 1 scheduled on 28/09/2026",
            "timing": {"dueAt": same, "startsAt": same, "endsAt": same, "loginByAt": same, "availabilityClosesAt": same}}],
        # Numeric dates are day first: 10/8/26 is 10 August, not 8 October.
        "DS viva": [{"intent": "new_work", "taskType": "test", "title": "DS viva", "subjectId": ds, "targeting": div,
            "timing": {"dateOnly": "2026-10-08"}, "evidence": "held in lab on 10/8/26"}],
        # A source stating no time of day: the model's midnight is a guess, not 5:30 am.
        "MDM test": [{"intent": "new_work", "taskType": "test", "title": "MDM test", "targeting": div,
            "timing": {"startsAt": "2026-10-31T00:00:00Z"}, "evidence": "conducted on 31st October 2026"}],
        # A range of days is due by its last day, even when the model calls it unresolved.
        "WDL practical exam": [{"intent": "new_work", "taskType": "test", "title": "WDL practical exam",
            "subjectId": wdl, "targeting": div, "evidence": "between 30 Nov and 4 Dec",
            "timing": {"mode": "unresolved", "dateWindowStart": "2026-11-30", "dateWindowEnd": "2026-12-04"}}],
        # Tentative alternatives bound the work as a range rather than leaving it undated.
        "Mini project": [{"intent": "new_work", "taskType": "assignment", "title": "Mini project presentation",
            "subjectId": wdl, "targeting": div, "evidence": "tentatively scheduled on 23rd/30th Sept 2026",
            "question": "Which date applies to you?", "timing": {"alternatives": ["2026-09-23", "2026-09-30"]}}],
    }  # fmt: skip
    for gid, subject, body, sent in [
        (
            "t1",
            "COA IA 1 scheduled on 28/09/2026 at 1:30 pm",
            "Log in to the LMS by 1:30 pm.",
            datetime(2026, 9, 27),
        ),
        ("t2", "DS viva", "Viva based on experiment 1 will be held in lab on 10/8/26.", datetime(2026, 8, 5)),
        ("t3", "MDM test", "The MDM test will be conducted on 31st October 2026.", now() - timedelta(days=2)),
        ("t4", "WDL practical exam", "Practical exam between 30 Nov and 4 Dec.", now() - timedelta(days=2)),
        (
            "t5",
            "Mini project",
            "Mini project tentatively scheduled on 23rd/30th Sept 2026.",
            datetime(2026, 9, 10),
        ),
    ]:
        send(fake, gid, "faculty.ds@somaiya.edu", (subject, body + " Division B."), sent.replace(tzinfo=UTC))
    conn = connect(client, headers, fake, "gmail")
    run(client, headers, conn)
    by_title = {t.title: t for t in tasks(student.uid)}
    coa_task = by_title["COA IA 1"]
    assert coa_task.due_at == ist(2026, 9, 28, 13, 30) and coa_task.data["timingMode"] == "fixed_session"
    assert coa_task.data["endsAt"] is None
    assert by_title["DS viva"].data["dueDate"] == "2026-08-10"
    mdm = by_title["MDM test"]
    assert mdm.data["dueDate"] == "2026-10-31" and mdm.due_at == ist(2026, 10, 31, 23, 59)
    wdl_task = by_title["WDL practical exam"]
    assert wdl_task.due_at == ist(2026, 12, 4, 23, 59) and wdl_task.data["dateWindowStart"] == "2026-11-30"
    assert wdl_task.data["timingProvenance"]["dueAt"]["basis"] == "source-window-end"
    mini = by_title["Mini project presentation"]
    assert mini.data["dateWindowStart"] == "2026-09-23" and mini.due_at == ist(2026, 9, 30, 23, 59)


def test_missing_dates_get_a_grounded_timing_only_look(client, headers, student, fake, model):
    subjects = setup_student(client, headers)
    ds, dsm = subjects["Data Structures"]["id"], subjects["Discrete Mathematics"]["id"]
    div = {"divisions": ["B"]}

    def item(title, subject, evidence):
        return [{"intent": "new_work", "taskType": "test" if "IA" in title else "assignment", "title": title,
                 "subjectId": subject, "targeting": div, "evidence": evidence}]  # fmt: skip

    model.items = {
        "DS assignment 4": item("DS assignment 4", ds, "DS assignment 4"),
        "DSM IA2": item("DSM IA2", dsm, "DSM IA2"),
        "Lab journal": item("Lab journal", ds, "Lab journal"),
        "DS assignment 5": item("DS assignment 5", ds, "DS assignment 5"),
        "ITVC worksheet due 22 Oct": item("ITVC worksheet due 22 Oct", None, "ITVC worksheet"),
    }
    model.timings = {
        "DS assignment 4": {"kind": "date", "role": "due", "date": "2026-10-16", "phrase": "by next Friday"},
        "DSM IA2": {
            "kind": "exact",
            "role": "start",
            "at": "2026-10-20T13:30:00+05:30",
            "phrase": "held on 20/10/2026 at 1:30 pm",
        },  # fmt: skip
        # A phrase the source does not contain is never accepted.
        "DS assignment 5": {"kind": "date", "role": "due", "date": "2026-10-25", "phrase": "by 25 October"},
    }
    t0 = now() - timedelta(days=1)
    for gid, subject, body in [
        ("m1", "DS assignment 4", "Submit DS assignment 4 by next Friday. Division B."),
        ("m2", "DSM IA2", "DSM IA2 will be held on 20/10/2026 at 1:30 pm in B115A. Division B."),
        ("m3", "Lab journal", "Complete the lab journal. Division B."),
        ("m4", "DS assignment 5", "Upload DS assignment 5 soon, before the due day. Division B."),
        ("m5", "ITVC worksheet due 22 Oct", "Solve the ITVC worksheet. Division B."),
    ]:
        send(fake, gid, "faculty.ds@somaiya.edu", (subject, body), t0)
    conn = connect(client, headers, fake, "gmail")
    run(client, headers, conn)
    by_title = {t.title: t for t in tasks(student.uid)}
    assert by_title["DS assignment 4"].data["dueDate"] == "2026-10-16"
    assert by_title["DSM IA2"].due_at == ist(2026, 10, 20, 13, 30)
    assert by_title["DS assignment 5"].due_at is None
    assert by_title["Lab journal"].due_at is None
    # A date in the item's own words is read without asking AI.
    assert by_title["ITVC worksheet due 22 Oct"].data["dueDate"] == "2026-10-22"
    asked = {title for call in model.timing_calls for title in call}
    assert "Lab journal" not in asked and "ITVC worksheet due 22 Oct" not in asked


def test_undated_work_is_repaired_once_without_new_tasks(client, headers, student, fake, model, monkeypatch):
    subjects = setup_student(client, headers)
    coa, dsm = subjects["Computer Organization & Architecture"]["id"], subjects["Discrete Mathematics"]["id"]
    div = {"divisions": ["B"]}
    same = "2026-10-01T13:30:00+05:30"
    model.items = {
        "DSM IA1 seating": [{"intent": "new_work", "taskType": "test", "title": "DSM IA1", "subjectId": dsm,
            "targeting": div, "evidence": "DSM IA1 scheduled on 1st October at 1:30 pm",
            "timing": {"startsAt": same, "endsAt": same}}],
        "COA IA2": [{"intent": "new_work", "taskType": "test", "title": "COA IA2", "subjectId": coa,
            "targeting": div, "evidence": "COA IA2"}],
    }  # fmt: skip
    t0 = now() - timedelta(days=1)
    send(
        fake,
        "r1",
        "faculty.ds@somaiya.edu",
        ("DSM IA1 seating", "DSM IA1 scheduled on 1st October at 1:30 pm. Div B."),
        t0,
    )
    send(
        fake,
        "r2",
        "faculty.ds@somaiya.edu",
        ("COA IA2", "COA IA2 will be held next Tuesday. Division B."),
        t0,
    )

    def unavailable(payload):
        raise ai.AIUnavailable("AI providers are temporarily unavailable")

    monkeypatch.setattr(ai, "resolve_timing", unavailable)
    conn = connect(client, headers, fake, "gmail")
    run(client, headers, conn)
    by_title = {t.title: t for t in tasks(student.uid)}
    assert by_title["COA IA2"].due_at is None  # The timing look could not run: kept, not lost.
    # Simulate DSM IA1 as an earlier interpreter left it: dated evidence, undated task.
    with transaction(student.uid) as db:
        task = db.get(Task, by_title["DSM IA1"].id)
        event = db.scalars(select(SourceEvent).where(SourceEvent.task_id == task.id)).one()
        event.processing_version = "phase3-interpret-2"
        omitted = {
            "basis": "source-timing-omitted",
            "evidenceRef": str(event.id),
            "sourceTime": t0.isoformat(),
        }
        task.data = {
            **{k: v for k, v in task.data.items() if k not in interpret.SCHEDULE_FIELDS},
            "timingMode": "undated",
            "timingProvenance": {k: omitted for k in interpret.SCHEDULE_FIELDS},
        }
        task.due_at = None
        db.commit()
    assert next(t for t in tasks(student.uid) if t.title == "DSM IA1").due_at is None
    monkeypatch.setattr(ai, "resolve_timing", model.timing)
    model.timings = {
        "COA IA2": {"kind": "date", "role": "start", "date": "2026-10-13", "phrase": "next Tuesday"}
    }
    run(client, headers, conn)
    after = tasks(student.uid)
    assert sorted(t.title for t in after) == ["COA IA2", "DSM IA1"]  # Repair never creates work.
    by_title = {t.title: t for t in after}
    assert by_title["DSM IA1"].due_at == ist(2026, 10, 1, 13, 30)  # From saved evidence, no AI.
    assert by_title["COA IA2"].data["dueDate"] == "2026-10-13"  # From a timing-only look.
    assert all(r.processing_state == "interpreted" and "retime" not in r.data for r in records(student.uid))
    calls = len(model.timing_calls)
    run(client, headers, conn)
    assert len(model.timing_calls) == calls  # Each task is repaired once per interpreter version.


def test_repair_that_cannot_reach_ai_never_holds_a_sync_open(
    client, headers, student, fake, model, monkeypatch
):
    subjects = setup_student(client, headers)
    coa = subjects["Computer Organization & Architecture"]["id"]
    model.items = {
        "COA IA2": [{"intent": "new_work", "taskType": "test", "title": "COA IA2", "subjectId": coa,
                     "targeting": {"divisions": ["B"]}, "evidence": "COA IA2"}],
    }  # fmt: skip
    send(fake, "z1", "faculty.ds@somaiya.edu", ("COA IA2", "COA IA2 next Tuesday. Division B."), now())

    def unavailable(payload):
        raise ai.AIUnavailable("AI providers are temporarily unavailable")

    monkeypatch.setattr(ai, "resolve_timing", unavailable)
    conn = connect(client, headers, fake, "gmail")
    run(client, headers, conn)
    model.down = True
    job = run(client, headers, conn)  # Queues the repair, whose first look pauses.
    for _ in range(interpret.RETIME_ATTEMPTS - 1):
        assert job["status"] == "waiting_retry"
        with transaction(student.uid) as db:
            for r in db.scalars(
                select(interpret.SourceRecord).where(interpret.SourceRecord.user_id == student.uid)
            ):
                r.data = {k: v for k, v in r.data.items() if k != "aiPausedUntil"}  # Let the retry fall due.
            pending = db.scalar(select(sync.SyncJob).where(sync.SyncJob.id == job["id"]))
            pending.next_retry_at = now() - timedelta(seconds=1)
            db.commit()
        for _ in range(10):
            job = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers).json()
            if job["status"] in ("completed", "waiting_retry"):
                break
    (record,) = records(student.uid)
    assert record.processing_state == "interpreted" and "retime" not in record.data
    assert job["status"] == "completed"
    assert [t.title for t in tasks(student.uid)] == ["COA IA2"]


def test_classroom_posts_add_only_assessments_tutorials_projects_and_presentations(
    client, headers, student, fake, model
):
    setup_student(client, headers)
    dbms = client.post("/api/v1/subjects", headers=headers, json={"name": "DBMS", "kind": "theory"}).json()[
        "id"
    ]
    recent = (now() - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    stamp = {"creationTime": recent, "updateTime": recent}

    def work(title, kind="assignment", **extra):
        return {
            "intent": "new_work",
            "taskType": kind,
            "title": title,
            "subjectId": dbms,
            "evidence": title,
            **extra,
        }

    fake.courses = [{"id": "c1", "name": "26-27 dbms Div B"}]
    fake.announcements["c1"] = [
        {**stamp, "id": "a1", "text": "Complete the writeup of experiment 4 before the next lab."},
        {**stamp, "id": "a2", "text": "DBMS IA1 quiz on 20 Oct at 1:30 pm."},
        {**stamp, "id": "a3", "text": "Mini Project Presentation on 25 Oct."},
        {**stamp, "id": "a4", "text": "Tutorial 3 is due on 22 Oct."},
    ]
    fake.coursework["c1"] = [
        {**stamp, "id": "w1", "title": "Experiment 9", "workType": "ASSIGNMENT",
         "description": "Perform Experiment 9. Also finish the Experiment 8 write-up.",
         "dueDate": {"year": 2026, "month": 10, "day": 18}, "dueTime": {"hours": 18, "minutes": 29}},
        {**stamp, "id": "w2", "title": "Lab manual", "workType": "MATERIAL",
         "description": "Experiment 10 write-up due Friday."},
    ]  # fmt: skip
    model.items = {
        "Complete the writeup of experiment 4 before the next lab.": [work("writeup of experiment 4")],
        "DBMS IA1 quiz on 20 Oct at 1:30 pm.": [work("DBMS IA1 quiz", "test")],
        "Mini Project Presentation on 25 Oct.": [work("Mini Project Presentation")],
        "Tutorial 3 is due on 22 Oct.": [{**work("Tutorial 3"), "evidence": "Tutorial 3 is due on 22 Oct."}],
        "Experiment 9": [work("Experiment 9"), work("Experiment 8 write-up")],
        "Lab manual": [work("Experiment 10 write-up")],
    }
    conn = connect(client, headers, fake, "classroom")
    run(client, headers, conn)
    client.put(f"/api/v1/subjects/{dbms}/classroom-mappings/{conn}/c1", headers=fresh(headers))
    run(client, headers, conn)
    # Stream text and materials add assessments, tutorials, projects and presentations only;
    # ordinary work comes from coursework the student turns in, never from text it mentions.
    by_title = {t.title: t for t in tasks(student.uid)}
    assert set(by_title) == {"DBMS IA1 quiz", "Mini Project Presentation", "Tutorial 3", "Experiment 9"}
    assert by_title["Tutorial 3"].data["dueDate"] == "2026-10-22"
    skipped = [r for r in records(student.uid) if r.provider_id.endswith(":a1")]
    assert skipped[0].processing_state == "ignored" and skipped[0].reason == "classroom_post_not_work"
    # A post still updates work already tracked from coursework.
    experiment = by_title["Experiment 9"]
    later = (now() - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    fake.announcements["c1"].append(
        {
            "id": "a5",
            "text": "Experiment 9 deadline extended to 30 Oct.",
            "creationTime": later,
            "updateTime": later,
        }
    )
    model.items["Experiment 9 deadline extended to 30 Oct."] = [
        {**work("Experiment 9"), "intent": "revision", "matchTaskId": str(experiment.id),
         "timing": {"dueAt": "2026-10-30T23:59:00+05:30"}}
    ]  # fmt: skip
    run(client, headers, conn)
    after = {t.title: t for t in tasks(student.uid)}
    assert len(after) == 4 and after["Experiment 9"].due_at == ist(2026, 10, 30, 23, 59)


def test_work_wrongly_attached_by_an_older_interpreter_becomes_its_own_task(
    client, headers, student, fake, model, auto, monkeypatch
):
    setup_student(client, headers)
    arvr = client.post("/api/v1/subjects", headers=headers, json={"name": "ARVR", "kind": "theory"}).json()[
        "id"
    ]

    def at(days):
        return (now() - timedelta(days=days)).isoformat().replace("+00:00", "Z")

    fake.courses = [{"id": "c1", "name": "ARVR MDM sem3"}]
    w13 = {
        "id": "w13",
        "title": "IA 2.13",
        "workType": "ASSIGNMENT",
        "creationTime": at(9),
        "updateTime": at(9),
        "dueDate": {"year": 2026, "month": 9, "day": 29},
        "dueTime": {"hours": 6, "minutes": 29},
    }
    w15 = {
        "id": "w15",
        "title": "IA 2.15 MCQ",
        "workType": "ASSIGNMENT",
        "creationTime": at(5),
        "updateTime": at(5),
        "dueDate": {"year": 2026, "month": 10, "day": 20},
        "dueTime": {"hours": 5},
    }
    turned = {"stateHistory": {"state": "TURNED_IN", "stateTimestamp": at(8)}}
    fake.coursework["c1"] = [w13]
    fake.submissions["c1"] = [
        {"id": "s13", "courseWorkId": "w13", "state": "TURNED_IN", "updateTime": at(8), "submissionHistory": [turned]}
    ]  # fmt: skip

    def matched_to_existing(payload):
        # The older interpreter trusted the model's suggested match without checking it.
        other = next((t["id"] for t in payload["candidateTasks"] if t["title"] == "IA 2.13"), None)
        return [{"intent": "new_work", "taskType": "assignment", "title": "IA 2.15 MCQ", "subjectId": arvr,
                 "evidence": "IA 2.15 MCQ", "matchTaskId": other}]  # fmt: skip

    model.items = {
        "IA 2.13": [
            {
                "intent": "new_work",
                "taskType": "assignment",
                "title": "IA 2.13",
                "subjectId": arvr,
                "evidence": "IA 2.13",
            }
        ],  # fmt: skip
        "IA 2.15 MCQ": matched_to_existing,
    }
    version, same_work = interpret.VERSION, interpret.same_work
    monkeypatch.setattr(interpret, "VERSION", "phase3-interpret-2")
    monkeypatch.setattr(interpret, "same_work", lambda cand, task, ctx: True)
    conn = connect(client, headers, fake, "classroom")
    run(client, headers, conn)
    client.put(f"/api/v1/subjects/{arvr}/classroom-mappings/{conn}/c1", headers=fresh(headers))
    run(client, headers, conn)
    fake.coursework["c1"].append(w15)  # Posted later, then matched to the earlier task.
    fake.submissions["c1"].append(
        {"id": "s15", "courseWorkId": "w15", "state": "CREATED", "updateTime": at(5)}
    )
    run(client, headers, conn)
    (glued,) = tasks(student.uid)  # The defect: one task, named after the newer work...
    assert glued.title == "IA 2.15 MCQ" and glued.completed_at  # ...completed by IA 2.13's turn-in.

    monkeypatch.setattr(interpret, "VERSION", version)  # The current interpreter, with its check.
    monkeypatch.setattr(interpret, "same_work", same_work)
    run(client, headers, conn)
    by_title = {t.title: t for t in tasks(student.uid)}
    assert set(by_title) == {"IA 2.13", "IA 2.15 MCQ"}
    mcq, other = by_title["IA 2.15 MCQ"], by_title["IA 2.13"]
    assert mcq.id == glued.id and mcq.completed_at is None  # Not turned in: no longer complete.
    assert mcq.due_at == datetime(2026, 10, 20, 5, 0, tzinfo=UTC)
    assert other.completed_at and other.due_at == datetime(2026, 9, 29, 6, 29, tzinfo=UTC)
    with transaction(student.uid) as db:
        actions = db.scalars(select(History.action).where(History.task_id == mcq.id)).all()
    assert "evidence_detached" in actions and "reopened" in actions
    run(client, headers, conn)  # Examined once: a later sync changes nothing.
    assert {t.title: t.revision for t in tasks(student.uid)} == {
        t.title: t.revision for t in by_title.values()
    }


def test_coursework_is_its_own_item_even_when_its_description_lists_other_work_first(
    client, headers, student, fake, model, auto, monkeypatch
):
    setup_student(client, headers)
    arvr = client.post("/api/v1/subjects", headers=headers, json={"name": "ARVR", "kind": "theory"}).json()[
        "id"
    ]
    stamp = (now() - timedelta(days=4)).isoformat().replace("+00:00", "Z")
    fake.courses = [{"id": "c1", "name": "ARVR MDM sem3"}]
    fake.coursework["c1"] = [
        {"id": "w8", "title": "IA 1.8 Compare OLED, LCD and Micro OLED", "workType": "ASSIGNMENT",
         "description": "Revise the reading notes first. Then compare OLED, LCD and Micro OLED.",
         "creationTime": stamp, "updateTime": stamp,
         "dueDate": {"year": 2026, "month": 10, "day": 20}, "dueTime": {"hours": 5}},
    ]  # fmt: skip
    turned = {"stateHistory": {"state": "TURNED_IN", "stateTimestamp": stamp}}
    fake.submissions["c1"] = [
        {
            "id": "s8",
            "courseWorkId": "w8",
            "state": "TURNED_IN",
            "updateTime": stamp,
            "submissionHistory": [turned],
        }
    ]

    def item(title):
        return {
            "intent": "new_work",
            "taskType": "assignment",
            "title": title,
            "subjectId": arvr,
            "evidence": title,
        }

    model.items = {
        "IA 1.8 Compare OLED, LCD and Micro OLED": [
            item("Reading notes"),
            item("IA 1.8 Compare OLED, LCD and Micro OLED"),
        ]
    }
    version, own_item = interpret.VERSION, interpret.own_item
    monkeypatch.setattr(interpret, "VERSION", "phase3-interpret-2")
    monkeypatch.setattr(interpret, "own_item", lambda items, title: 0)  # The older rule: the first item.
    conn = connect(client, headers, fake, "classroom")
    run(client, headers, conn)
    client.put(f"/api/v1/subjects/{arvr}/classroom-mappings/{conn}/c1", headers=fresh(headers))
    run(client, headers, conn)
    before = {t.title: t for t in tasks(student.uid)}
    # The defect: the first listed item took the coursework's identity and its turn-in.
    assert before["Reading notes"].completed_at
    assert not before["IA 1.8 Compare OLED, LCD and Micro OLED"].completed_at

    monkeypatch.setattr(interpret, "VERSION", version)
    monkeypatch.setattr(interpret, "own_item", own_item)
    run(client, headers, conn)
    by_title = {t.title: t for t in tasks(student.uid)}
    coursework = by_title["IA 1.8 Compare OLED, LCD and Micro OLED"]
    assert coursework.completed_at and coursework.due_at == datetime(2026, 10, 20, 5, 0, tzinfo=UTC)
    assert coursework.id == before["IA 1.8 Compare OLED, LCD and Micro OLED"].id  # No duplicate.
    assert by_title["Reading notes"].completed_at is None  # Its turn-in was the coursework's.
    run(client, headers, conn)  # Repaired once.
    assert len(tasks(student.uid)) == 2


def test_tasks_get_clean_names_that_keep_identifiers_and_never_override_the_student(
    client, headers, student, fake, model, monkeypatch
):
    from duecare import naming
    from tests.conftest import AI_NAME_TITLES

    calls = []

    def provider(system, user, schema):
        tasks_ = json.loads(user)["tasks"]
        calls.append([t["title"] for t in tasks_])
        proposals = {
            "COA IA 1 scheduled on 28/09/2026 at 1:30 pm": "COA IA 1",
            "Experiment 8- TCL and DCL commands": "Experiment 8: TCL and DCL Commands",
            "IA 2.15 MCQ": "IA 2.16 MCQ",  # Changes an identifier: rejected for the tidy-up.
        }
        items = [{"key": t["key"], "name": proposals.get(t["title"])} for t in tasks_]
        return schema.model_validate({"items": items}), {"provider": "fake"}

    monkeypatch.setattr(naming, "name_titles", AI_NAME_TITLES)
    monkeypatch.setattr(ai, "structured", provider)
    subjects = setup_student(client, headers)
    coa = subjects["Computer Organization & Architecture"]["id"]
    div = {"divisions": ["B"]}
    titles = [
        "COA IA 1 scheduled on 28/09/2026 at 1:30 pm",
        "Experiment 8- TCL and DCL commands",
        "IA 2.15 MCQ",
    ]
    model.items = {
        t: [{"intent": "new_work", "taskType": "assignment", "title": t, "subjectId": coa, "targeting": div, "evidence": t}]
        for t in titles
    }  # fmt: skip
    for n, t in enumerate(titles):
        send(fake, f"n{n}", "faculty.coa@somaiya.edu", (t, t + ". Division B."), now() - timedelta(days=1))
    conn = connect(client, headers, fake, "gmail")
    run(client, headers, conn)
    shown = {t["sourceTitle"]: t for t in client.get("/api/v1/tasks", headers=headers).json()["items"]}
    assert shown[titles[0]]["title"] == "COA IA 1"
    assert shown[titles[1]]["title"] == "Experiment 8: TCL and DCL Commands"
    assert shown[titles[2]]["title"] == "IA 2.15 MCQ"
    # The clean name is searchable; the student's own title always wins.
    found = client.get("/api/v1/tasks?q=TCL and DCL Commands", headers=headers).json()["items"]
    assert [t["sourceTitle"] for t in found] == [titles[1]]
    task = shown[titles[0]]
    edited = client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=fresh(headers),
        json={"revision": task["revision"], "title": "My COA quiz"},
    ).json()
    assert edited["title"] == "My COA quiz"
    calls.clear()
    run(client, headers, conn)
    assert calls == []  # Named once; a student-named task is never renamed.

    # Source details: who posted it, when, and a link back to the original.
    (source,) = [
        e
        for e in client.get(f"/api/v1/tasks/{task['id']}/evidence", headers=headers).json()["items"]
        if e["state"] == "active"
    ]
    assert source["sender"] == "faculty.coa@somaiya.edu" and source["postedAt"]
    assert source["openUrl"].startswith("https://mail.google.com/mail/u/?authuser=student%40somaiya.edu#all/")


def test_tasks_imported_before_naming_get_clean_names_on_a_later_sync(client, headers, student, fake, model):
    subjects = setup_student(client, headers)
    coa = subjects["Computer Organization & Architecture"]["id"]
    title = "Re: COA IA 1 scheduled on 28/09/2026 at 1:30 pm"
    model.items = {
        title: [{"intent": "new_work", "taskType": "test", "title": title, "subjectId": coa,
                 "targeting": {"divisions": ["B"]}, "evidence": "COA IA 1"}]
    }  # fmt: skip
    send(fake, "old", "faculty.coa@somaiya.edu", (title, "COA IA 1. Division B."), now() - timedelta(days=1))
    conn = connect(client, headers, fake, "gmail")
    run(client, headers, conn)
    with transaction(student.uid) as db:  # As imported before names existed.
        (task,) = db.scalars(select(Task)).all()
        task.data = {k: v for k, v in task.data.items() if k not in ("displayTitle", "naming")}
        db.commit()
    assert client.get("/api/v1/tasks", headers=headers).json()["items"][0]["title"] == title
    run(client, headers, conn)
    assert client.get("/api/v1/tasks", headers=headers).json()["items"][0]["title"] == "COA IA 1"


@pytest.mark.parametrize("granted", [True, False])
def test_classroom_sources_name_the_teacher_only_when_allowed(client, headers, student, fake, model, granted):
    from duecare.google import IDENTITY_SCOPES, OPTIONAL_SCOPES, SERVICE_SCOPES

    rosters = OPTIONAL_SCOPES["classroom"]
    if granted:
        fake.scopes = [*IDENTITY_SCOPES, *SERVICE_SCOPES["classroom"], *rosters]
    else:  # Google refuses the teacher lookup without the permission.
        fake.failures += [("teachers:c1", "permission")] * 2  # Once per sync.
    dbms = client.post("/api/v1/subjects", headers=headers, json={"name": "DBMS", "kind": "theory"}).json()[
        "id"
    ]
    stamp = (now() - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    fake.courses = [
        {"id": "c1", "name": "DBMS B2 116A", "alternateLink": "https://classroom.google.com/c/c1"}
    ]
    fake.teachers["c1"] = [{"userId": "t1", "profile": {"name": {"fullName": "Sheetal Pereira"}}}]
    fake.coursework["c1"] = [
        {"id": "w8", "title": "Experiment 8", "workType": "ASSIGNMENT", "creatorUserId": "t1",
         "alternateLink": "https://classroom.google.com/c/c1/a/w8", "creationTime": stamp, "updateTime": stamp,
         "dueDate": {"year": 2026, "month": 10, "day": 20}, "dueTime": {"hours": 18, "minutes": 29}}
    ]  # fmt: skip
    model.items = {"Experiment 8": []}
    conn = connect(client, headers, fake, "classroom")
    run(client, headers, conn)
    client.put(f"/api/v1/subjects/{dbms}/classroom-mappings/{conn}/c1", headers=fresh(headers))
    assert run(client, headers, conn)["status"] == "completed"  # A missing permission never blocks sync.
    (connection,) = client.get("/api/v1/connections", headers=headers).json()["items"]
    assert connection["optionalPermissionsMissing"] == ([] if granted else rosters)
    (task,) = client.get("/api/v1/tasks", headers=headers).json()["items"]
    (source,) = client.get(f"/api/v1/tasks/{task['id']}/evidence", headers=headers).json()["items"]
    assert source["courseName"] == "DBMS B2 116A"
    assert source["postedBy"] == ("Sheetal Pereira" if granted else None)
    assert source["openUrl"] == "https://classroom.google.com/c/c1/a/w8"


def test_posts_imported_before_teacher_names_were_allowed_get_their_teacher(
    client, headers, student, fake, model
):
    from duecare.google import IDENTITY_SCOPES, OPTIONAL_SCOPES, SERVICE_SCOPES
    from duecare.models import SourceRecord

    dbms = client.post("/api/v1/subjects", headers=headers, json={"name": "DBMS", "kind": "theory"}).json()[
        "id"
    ]

    def at(days):
        return (now() - timedelta(days=days)).isoformat().replace("+00:00", "Z")

    fake.courses = [{"id": "c1", "name": "DBMS B2 116A"}]
    fake.teachers["c1"] = [{"userId": "t1", "profile": {"name": {"fullName": "Sheetal Pereira"}}}]
    fake.coursework["c1"] = [
        {"id": "w7", "title": "Experiment 7", "workType": "ASSIGNMENT", "creatorUserId": "t1",
         "creationTime": at(20), "updateTime": at(20), "dueDate": {"year": 2026, "month": 10, "day": 25},
         "dueTime": {"hours": 18, "minutes": 29}},
        {"id": "w8", "title": "Experiment 8", "workType": "ASSIGNMENT", "creatorUserId": "t1",
         "creationTime": at(2), "updateTime": at(2), "dueDate": {"year": 2026, "month": 10, "day": 26},
         "dueTime": {"hours": 18, "minutes": 29}},
    ]  # fmt: skip
    model.items = {"Experiment 7": [], "Experiment 8": []}
    fake.failures += [("teachers:c1", "permission")] * 2
    conn = connect(client, headers, fake, "classroom")
    run(client, headers, conn)
    client.put(f"/api/v1/subjects/{dbms}/classroom-mappings/{conn}/c1", headers=fresh(headers))
    run(client, headers, conn)
    with transaction(student.uid) as db:  # As stored before posters were recorded.
        for record in db.scalars(select(SourceRecord).where(SourceRecord.kind == "classroom_coursework")):
            record.data = {k: v for k, v in record.data.items() if k != "creatorUserId"}
        db.commit()
    # The student allows teacher names: the next sync lists the course in full once.
    fake.scopes = [*IDENTITY_SCOPES, *SERVICE_SCOPES["classroom"], *OPTIONAL_SCOPES["classroom"]]
    connect(client, headers, fake, "classroom", code="c2")
    run(client, headers, conn)
    by_title = {t["sourceTitle"]: t for t in client.get("/api/v1/tasks", headers=headers).json()["items"]}
    old = by_title["Experiment 7"]
    (source,) = client.get(f"/api/v1/tasks/{old['id']}/evidence", headers=headers).json()["items"]
    assert source["postedBy"] == "Sheetal Pereira"
