"""Synthetic authentication and Google source adapters for local browser tests only; not a runtime mode."""

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json

from duecare import auth, google
from duecare.models import now
from tests.conftest import FixtureAuth, account
from tests.conftest import app as app
from tests.fake_google import FakeGoogle, eml

fixture = account("browser-fixture@somaiya.edu")
sources_fixture = account("browser-sources@somaiya.edu")
attention_fixture = account("browser-attention@somaiya.edu")
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
(Path(__file__).resolve().parents[3] / ".local/e2e-account.json").write_text(
    json.dumps(
        {
            "handle": fixture.handle,
            "sourcesHandle": sources_fixture.handle,
            "attentionHandle": attention_fixture.handle,
        }
    )
)
