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
    json.dumps({"handle": fixture.handle, "sourcesHandle": sources_fixture.handle})
)
