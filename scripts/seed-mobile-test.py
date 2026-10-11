"""Seed only the isolated synthetic API for Android emulator integration tests."""

import datetime
import importlib
import json
import os
import pathlib
import sys
import urllib.request
import uuid

root = pathlib.Path(__file__).resolve().parents[1]
from urllib.parse import urlparse

config_path = root / ".local/test-config.json"
local_config = json.loads(config_path.read_text())
for name in ("DATABASE_URL", "MIGRATION_DATABASE_URL"):
    target = urlparse(local_config[name])
    if (target.hostname, target.port, target.path) != (
        "127.0.0.1",
        55432,
        "/duecare_test",
    ):
        raise SystemExit(
            "Mobile fixtures require the isolated local test database on port 55432."
        )
a = json.loads((root / ".local/e2e-account.json").read_text())


def call(path, body=None, method=None):
    req = urllib.request.Request(
        "http://127.0.0.1:8001/api/v1" + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": "Bearer " + a["handle"],
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


p = call("/me")
if p["identity"]["email"] != "browser-fixture@somaiya.edu":
    raise SystemExit("Refusing to modify an account outside the synthetic E2E server.")
call(
    "/me",
    {
        "revision": p["revision"],
        "branchCode": "COMPS",
        "classYear": "SY",
        "currentSemester": 3,
        "division": "B",
        "generalBatch": "2",
        "rollNumber": "TEST01",
        # MOBILE_TEST_THEME=dark checks the dark palette on the device.
        "theme": os.environ.get("MOBILE_TEST_THEME", "light"),
    },
    "PATCH",
)
subjects = call("/subjects")["items"]
subject = next(
    (s for s in subjects if s["name"] == "Database Management Systems"), None
) or call(
    "/subjects",
    {"name": "Database Management Systems", "kind": "theory", "code": "DBMS"},
)
now = datetime.datetime.now(datetime.timezone.utc)
existing = call("/tasks")["items"]
tasks = []
for title, hours, status in [
    ("DBMS ER diagram", 30, "due"),
    ("OS write-up", -3, "due"),
    ("Prepare for DBMS test", 72, "due"),
    ("Read chapter 4", None, "completed"),
]:
    t = next((t for t in existing if t["title"] == title), None)
    if t is None:
        t = call(
            "/tasks",
            {
                "title": title,
                "type": "test" if "test" in title else "assignment",
                "subjectId": subject["id"],
                "instructions": "Synthetic emulator test: draw the ER diagram for the library system.",
                "notes": "Local test data only.",
                "timingMode": "deadline_only" if hours is not None else "undated",
                "dueAt": (now + datetime.timedelta(hours=hours)).isoformat()
                if hours is not None
                else None,
            },
        )
    if t["status"] != status and (status == "completed" or t["status"] == "completed"):
        t = call(
            "/tasks/" + t["id"], {"revision": t["revision"], "status": status}, "PATCH"
        )
    tasks.append({"id": t["id"], "title": t["title"]})
sid = subject["id"]
tt = call("/subjects/" + sid + "/timetable")
call(
    "/subjects/" + sid + "/timetable",
    {
        "revision": tt["revision"],
        "slots": [
            {
                "weekday": datetime.datetime.now(
                    datetime.timezone(datetime.timedelta(hours=5, minutes=30))
                ).isoweekday(),
                "startTime": "09:00",
                "endTime": "10:00",
                "location": "601",
            }
        ],
    },
    "PUT",
)
sys.path.insert(0, str(root / "apps/api"))
fixtures = importlib.import_module("tests.conftest")
if fixtures.config != local_config:
    raise SystemExit("Synthetic test configuration changed while seeding.")
from duecare.common import work
from duecare.models import ReviewItem
from sqlalchemy import select

with work({"id": p["id"]}) as db:
    r = db.scalar(select(ReviewItem).where(ReviewItem.user_id == uuid.UUID(p["id"])))
    if r is None:
        r = ReviewItem(
            user_id=uuid.UUID(p["id"]),
            task_id=uuid.UUID(tasks[0]["id"]),
            issue_type="conflict",
            question="Synthetic review: keep your current assignment details?",
            data={
                "sourceKind": "classroom_coursework",
                "excerpt": "Local emulator test evidence. No real Google account was read.",
                "conflicts": {
                    "title": {
                        "current": "DBMS ER diagram",
                        "proposed": "Revised DBMS diagram",
                    }
                },
            },
        )
        db.add(r)
    else:
        r.status = "open"
        r.resolved_at = None
        r.revision += 1
    db.flush()
    review = str(r.id)
(root / ".local/mobile-fixture.json").write_text(
    json.dumps({"subject": sid, "tasks": tasks, "reviewId": review})
)
defines = root / ".local/mobile-debug-defines.json"
defines.write_text(
    json.dumps({"API_URL": "http://10.0.2.2:8001", "DEV_SESSION": a["handle"]})
)
defines.chmod(0o600)
print("Synthetic mobile fixture and debug configuration ready.")
