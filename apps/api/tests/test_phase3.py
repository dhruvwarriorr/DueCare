"""Phase 3: interpretation, academic targeting, review, rules, reconciliation, and completion.

Fixtures are synthetic, redacted messages modelled on the catalogued LMS templates and faculty
notices (specification section 6). The AI provider is faked; no external calls are made.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pytest
from sqlalchemy import func, select

from duecare import ai, google, interpret, targeting
from duecare.config import settings
from duecare.db import transaction
from duecare.domain import effective_status
from duecare.models import ReviewItem, SourceEvent, Task, now
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

    def __call__(self, payload):
        key = payload["source"].get("subject") or payload["source"].get("title")
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
        gid, eml(sender, subject, body, f"<{gid}@test>", sent=sent, headers=headers, to=to), ts=sent
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
    assert job["status"] == "completed" and job["progress"].get("reviews") == 1, (
        job["progress"],
        [
            (r.processing_state, r.reason, (r.data.get("interpretation") or {}).get("outcomes"))
            for r in records(student.uid)
        ],
    )
    # "Data Structures" matches both the theory and the lab subject: ask, never guess.
    (item,) = reviews(client, headers)
    assert item["issueType"] == "choose_subject" and len(item["subjectChoices"]) == 2
    assert tasks(student.uid) == []
    out = resolve(
        client,
        headers,
        item,
        action="accept",
        subjectId=subjects["Data Structures Laboratory"]["id"],
        rememberAlias=True,
    )
    (task,) = tasks(student.uid)
    assert (
        task.type == "assignment"
        and task.due_at == ist(2026, 9, 21, 23, 59)
        and out["taskId"] == str(task.id)
    )
    assert effective_status(task, now()) == "overdue"
    lab = client.get(
        "/api/v1/subjects/" + subjects["Data Structures Laboratory"]["id"], headers=headers
    ).json()
    assert lab["lmsCourseLabels"] == ["Data Structures_B_ODD_26-27"]

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


def test_receipt_without_enabled_path_asks_once_and_invalid_receipts_never_complete(
    client, headers, student, fake
):
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
    resolve(
        client,
        headers,
        reviews(client, headers)[0],
        action="accept",
        subjectId=subjects["Data Structures Laboratory"]["id"],
    )
    send(
        fake,
        "r1",
        LMS,
        receipt("EXP7-Graph", "DS_B_ODD_26-27", 92000, "a.docx"),
        now() - timedelta(days=1),
        [AUTH],
    )
    send(
        fake,
        "r2",
        LMS,
        receipt("EXP7-Graph", "DS_B_ODD_26-27", 92000, "b.docx"),
        now() - timedelta(hours=5),
        [AUTH],
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
    confirm = [r for r in open_items if r["issueType"] == "confirm_completion"]
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
    resolve(
        client,
        headers,
        reviews(client, headers)[0],
        action="accept",
        subjectId=subjects["Data Structures Laboratory"]["id"],
    )
    r = client.post(f"/api/v1/connections/{conn}/reprocess", headers=fresh(headers))
    job = r.json()["job"]
    while job["status"] not in ("completed", "failed"):
        job = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers).json()
    (task,) = tasks(student.uid)
    assert task.completed_at  # Reprocessing matched the receipt that was unmatched before the task existed.
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
    assert set(titles) == {"DS Lab OST", "COA IA1 quiz"}
    ost = titles["DS Lab OST"]
    assert ost.data["startsAt"] == "2026-10-13T03:30:00+00:00" and ost.due_at == ist(
        2026, 10, 13, 9, 0
    )  # Explicit 09:00 kept.
    coa_task = titles["COA IA1 quiz"]
    assert coa_task.data["loginByAt"] != coa_task.data["startsAt"] and coa_task.data["location"] == "B115A"
    assert coa_task.data["rulePriority"]["value"] == "high"
    assert client.get(f"/api/v1/tasks/{coa_task.id}", headers=headers).json()["priority"] == "high"
    open_items = {r["issueType"]: r for r in reviews(client, headers)}
    assert set(open_items) == {"timing_unresolved", "choose_subject"}  # ESE window; invalid AI subject id.
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
    assert job["status"] == "completed" and job["progress"]["aiPaused"] == 2
    # Template work continued without AI; AI items paused without losing successful results.
    assert [r["issueType"] for r in reviews(client, headers)] == ["choose_subject"]
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
        db.commit()
    run(client, headers, conn)
    assert "Quiz announcement" not in model.calls and "COA assignment 2" in model.calls
    assert [t.title for t in tasks(student.uid)] == ["COA assignment 2"]


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
    assert ia.completed_at is None and effective_status(ia, now()) == "overdue"
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
    resolve(
        client,
        headers,
        reviews(client, headers)[0],
        action="accept",
        subjectId=subjects["Data Structures Laboratory"]["id"],
    )
    r = client.post(f"/api/v1/connections/{conn}/reprocess", headers=fresh(headers))
    job = r.json()["job"]
    while job["status"] not in ("completed", "failed"):
        job = client.post(f"/api/v1/sync-jobs/{job['id']}/advance", headers=headers).json()
    (imported,) = tasks(student.uid)
    assert imported.completed_at
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

    setup_student(client, headers)
    send(
        fake,
        "d",
        LMS,
        reminder("EXP11", "Monday, 26 October 2026 11:59 PM IST", 96000),
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
