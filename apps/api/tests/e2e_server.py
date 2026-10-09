"""Synthetic authentication and Google source adapters for local browser tests only; not a runtime mode."""

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json

from duecare import academic, auth, google
from duecare.common import work
from duecare.models import Connection, Subject, now
from duecare.sources_api import link_account
from duecare.views import profile
from tests.conftest import FixtureAuth, account
from tests.conftest import app as app
from tests.fake_google import FakeGoogle, eml
from tests.scheduler_png import screenshot
from tests.test_phase4 import imported
from tests.test_timetable_import import WEEK
from tests.timetable_pdf import sample

fixture = account("browser-fixture@somaiya.edu")
sources_fixture = account("browser-sources@somaiya.edu")
attention_fixture = account("browser-attention@somaiya.edu")
privacy_fixture = account("browser-privacy@somaiya.edu")
delete_fixture = account("browser-delete@somaiya.edu")
source_delete_fixture = account("browser-source-delete@somaiya.edu")
timetable_fixture = account("browser-timetable@somaiya.edu")
scheduler_fixture = account("browser-scheduler@somaiya.edu")
auth.provider = FixtureAuth()

# Synthetic, redacted source data. No real mail, accounts, or Google requests are involved.
source = FakeGoogle()
source.service = "gmail"
recent = now() - timedelta(days=1)
source.add_message(
    "e1", eml("lms-notices@somaiya.edu", "Synthetic lab notice", "Lab test details", "<e1@test>"), ts=recent
)
source.add_message("e2", eml("newsletter@shop.example", "Sale", "Not academic", "<e2@test>"), ts=recent)
source.add_message(
    "e3", eml("blocked.sender@somaiya.edu", "Blocked notice", "Never fetched", "<e3@test>"), ts=recent
)
# Synthetic LMS reminder and receipt modelled on the catalogued templates (no real identities).
lms_host = "https://lms-kjsce.somaiya.edu"
reminder = "[LMS-Reminder] (DS_B_ODD_26-27-Assignment) EXP3-Queue is due"
source.add_message(
    "e4",
    eml(
        "lms-kjsse@somaiya.edu",
        reminder,
        f"{reminder}\n\nWhen | Monday, 26 October 2026 11:59 PM IST\n\nCourse | Data Structures_B_ODD_26-27\n\n"
        f"Activity | Assignment: EXP3-Queue\n\n{lms_host}/mod/assign/view.php?id=70001\n",
        "<e4@test>",
        to="personal.gmail@example.com",
    ),
    ts=recent - timedelta(hours=2),
)
source.add_message(
    "e5",
    eml(
        "lms-kjsse@somaiya.edu",
        "Assignment submission confirmation - EXP3-Queue",
        "DS_B_ODD_26-27 -> Assignment -> EXP3-Queue\n-----\nYou have submitted an assignment submission for "
        f"'EXP3-Queue'.\n\n{lms_host}/mod/assign/view.php?id=70001\n\nFile submissions\n* queue.c (2 KB)\n",
        "<e5@test>",
        to="personal.gmail@example.com",
        headers=[
            (
                "Authentication-Results",
                "mx.google.com; dkim=pass header.i=@somaiya.edu; dmarc=pass (p=NONE) header.from=somaiya.edu",
            )
        ],
    ),
    ts=recent - timedelta(hours=1),
)
source.courses = [
    {"id": "course-1", "name": "Synthetic Databases Div B", "section": "B", "courseState": "ACTIVE"}
]
stamp = (now() - timedelta(days=2)).isoformat().replace("+00:00", "Z")
source.coursework["course-1"] = [
    {"id": "work-1", "title": "Synthetic experiment", "creationTime": stamp, "updateTime": stamp}
]


def exchange(code, verifier):
    # The browser test selects the service through the authorization code it supplies.
    source.service = "classroom" if code.startswith("classroom") else "gmail"
    source.identity_claims = {
        "sub": "browser-source-" + source.service,
        "email": f"personal.{source.service}@example.com",
        "email_verified": True,
    }
    return FakeGoogle.exchange(source, code, verifier)


source.exchange = exchange
google.provider = source
# A disconnected synthetic source isolates privacy workflows from browser-driven sync.
with work({"id": str(source_delete_fixture.uid)}) as db:
    linked = link_account(
        db,
        source_delete_fixture.uid,
        "privacy-google",
        "privacy@example.com",
        {},
        {
            "refresh_token": "synthetic-refresh",
            "access_token": "synthetic-access",
            "expires_in": 3600,
            "scope": " ".join(google.SERVICE_SCOPES["gmail"]),
        },
        ["gmail"],
    )
    privacy_connection = linked["connectionId"]
    db.get(Connection, __import__("uuid").UUID(privacy_connection)).status = "disconnected"
removed_task, _, _ = imported(source_delete_fixture.uid, privacy_connection, "privacy-remove")
retained_task, _, _ = imported(source_delete_fixture.uid, privacy_connection, "privacy-keep", manual=True)
# A division B, batch 2 student with subjects to link, and a synthetic timetable PDF to upload.
with work({"id": str(timetable_fixture.uid)}) as db:
    p = profile(db, str(timetable_fixture.uid))
    p.data = academic.profile_data(
        {
            "branchCode": "COMPS",
            "classYear": "SY",
            "currentSemester": 3,
            "division": "B",
            "generalBatch": "2",
            "rollNumber": "001A",
        }
    )
    p.revision = 2
    for name, kind, code in [
        ("Data Structures", "theory", "DS"),
        ("Data Structures Lab", "lab", None),
        ("Database Management Systems", "theory", "DBMS"),
        ("Database Management Systems Lab", "lab", None),
        ("Computer Organization and Architecture", "theory", None),
    ]:
        db.add(
            Subject(user_id=timetable_fixture.uid, name=name, kind=kind, data={"code": code, "aliases": []})
        )
(Path(__file__).resolve().parents[3] / ".local/e2e-timetable.pdf").write_bytes(sample())
# A scheduler user with subjects, and two overlapping Week-view screenshots.
with work({"id": str(scheduler_fixture.uid)}) as db:
    p = profile(db, str(scheduler_fixture.uid))
    p.data = academic.profile_data(
        {
            "branchCode": "COMPS",
            "classYear": "SY",
            "currentSemester": 3,
            "division": "B",
            "generalBatch": "2",
            "rollNumber": "002A",
        }
    )
    p.revision = 2
    for name, kind in [
        ("Data Structures", "theory"),
        ("Data Structures Lab", "lab"),
        ("Introduction to Virtual Reality and Unity Game Engine", "theory"),
    ]:
        db.add(Subject(user_id=scheduler_fixture.uid, name=name, kind=kind, data={"aliases": []}))
for n, (start, end) in enumerate([(420, 715), (690, 985)], start=1):
    screenshot(start, end, WEEK).save(Path(__file__).resolve().parents[3] / f".local/e2e-scheduler-{n}.png")
(Path(__file__).resolve().parents[3] / ".local/e2e-account.json").write_text(
    json.dumps(
        {
            "handle": fixture.handle,
            "sourcesHandle": sources_fixture.handle,
            "attentionHandle": attention_fixture.handle,
            "privacyHandle": privacy_fixture.handle,
            "deleteHandle": delete_fixture.handle,
            "sourceDeleteHandle": source_delete_fixture.handle,
            "timetableHandle": timetable_fixture.handle,
            "schedulerHandle": scheduler_fixture.handle,
            "removedTask": removed_task,
            "retainedTask": retained_task,
        }
    )
)
