"""Synthetic authentication adapter for local browser tests only; not a runtime mode."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json

from duecare import auth
from tests.conftest import FixtureAuth, account
from tests.conftest import app as app

fixture = account("browser-fixture@somaiya.edu")
auth.provider = FixtureAuth()
(Path(__file__).resolve().parents[3] / ".local/e2e-account.json").write_text(
    json.dumps({"handle": fixture.handle})
)
