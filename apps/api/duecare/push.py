"""Push notifications to the mobile app through Firebase Cloud Messaging (HTTP v1).

Messages are data-only and content-free: what kind of thing happened and how often, never a title,
sender or source text. The app wakes up, fetches the details over its own session and writes the
notification itself. The same wake-up refreshes the deadline reminders it schedules on the phone, so
a push is also sent (silently) when tasks change with nothing to announce.
"""

import base64
import hashlib
import json
import logging
import time
import uuid
from collections import Counter
from datetime import timedelta
from threading import Lock
from typing import Literal

import httpx
import jwt
from pydantic import Field, field_validator
from sqlalchemy import func, select

from .common import work
from .config import settings
from .errors import ApiError
from .models import Activity, NotificationSettings, PushDevice, Task, now
from .schemas import Input

log = logging.getLogger("duecare.push")

# Activity event types and the notification setting that controls each.
CATEGORIES = {
    "new_task": "new_work",
    "revision": "changes",
    "reopened": "changes",
    "review": "review",
    "auto_completed": "completed",
    "sync_issue": "sync_issues",
}
LEADS = {10080, 4320, 1440, 360, 180, 60, 30}  # Minutes before a deadline the app can remind.
# A sync can add many tasks in a burst: wait until it settles so they arrive as one notification,
# but never hold a change back for more than two minutes.
SETTLE = timedelta(seconds=15)
LONGEST_WAIT = timedelta(minutes=2)
TIME = r"^([01]\d|2[0-3]):[0-5]\d$"


class Preferences(Input):
    """What the student wants to hear about. Reminders, the daily summary and quiet hours are
    applied on the phone; the server uses push and the update categories."""

    push: bool = True
    new_work: bool = True
    changes: bool = True
    review: bool = True
    completed: bool = True
    sync_issues: bool = True
    reminders: bool = True
    reminder_leads: list[int] = Field(default_factory=lambda: [1440, 60], min_length=1, max_length=7)
    reminder_scope: Literal["all", "important"] = "all"
    digest: bool = False
    digest_time: str = Field("08:00", pattern=TIME)
    quiet_hours: bool = False
    quiet_start: str = Field("22:00", pattern=TIME)
    quiet_end: str = Field("07:00", pattern=TIME)

    @field_validator("reminder_leads")
    @classmethod
    def known_leads(cls, value):
        if not set(value) <= LEADS:
            raise ValueError("Choose reminder times from the list")
        return sorted(set(value), reverse=True)


def preferences(data):
    """Saved choices over today's defaults; unknown or invalid saved values fall back."""
    try:
        return Preferences.model_validate(data or {})
    except ValueError:
        return Preferences()


def owner_hash(uid):
    """Lets the app ignore a push meant for an account that has since signed out of the phone."""
    return hashlib.sha256(str(uid).encode()).hexdigest()[:16]


class Fcm:
    """Minimal FCM HTTP v1 client authenticated with a Firebase service account."""

    scope = "https://www.googleapis.com/auth/firebase.messaging"

    def __init__(self, account):
        self.account = account
        self.project = account["project_id"]
        self._token, self._expires = None, 0.0
        self._lock = Lock()

    def access_token(self):
        with self._lock:
            if self._token and time.time() < self._expires - 60:
                return self._token
            issued = int(time.time())
            assertion = jwt.encode(
                {
                    "iss": self.account["client_email"],
                    "scope": self.scope,
                    "aud": self.account.get("token_uri", "https://oauth2.googleapis.com/token"),
                    "iat": issued,
                    "exp": issued + 3600,
                },
                self.account["private_key"],
                algorithm="RS256",
            )
            response = httpx.post(
                self.account.get("token_uri", "https://oauth2.googleapis.com/token"),
                data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
                timeout=15,
            )
            response.raise_for_status()
            body = response.json()
            self._token, self._expires = body["access_token"], issued + int(body.get("expires_in", 3600))
            return self._token

    def send(self, token, data, urgent):
        """'sent', 'invalid' (forget this token) or 'retry'."""
        try:
            response = httpx.post(
                f"https://fcm.googleapis.com/v1/projects/{self.project}/messages:send",
                headers={"Authorization": "Bearer " + self.access_token()},
                json={
                    "message": {
                        "token": token,
                        "data": data,
                        # High priority wakes the phone for something to show; a silent refresh
                        # can wait for the phone's next maintenance window.
                        "android": {"priority": "high" if urgent else "normal", "ttl": "86400s"},
                    }
                },
                timeout=15,
            )
        except httpx.HTTPError as exc:
            log.warning("push send unavailable type=%s", type(exc).__name__)
            return "retry"
        if response.status_code == 200:
            return "sent"
        if response.status_code in (404, 400, 403):
            status = response.json().get("error", {}).get("status", "") if response.content else ""
            if status in ("NOT_FOUND", "UNREGISTERED", "INVALID_ARGUMENT", "SENDER_ID_MISMATCH"):
                return "invalid"
        log.warning("push rejected status=%s", response.status_code)
        return "retry"


_client = None


def client():
    """The configured FCM client, or None when push is not set up."""
    global _client
    raw = settings().fcm_service_account.strip()
    if not raw:
        return None
    if _client is None:
        try:
            account = json.loads(raw if raw.startswith("{") else base64.b64decode(raw))
            _client = Fcm(account)
        except (ValueError, KeyError):
            log.warning("push configuration unreadable")
            return None
    return _client


def configured():
    return client() is not None


def message(kind, uid, counts=None, at=None):
    """FCM data values must be strings."""
    return {
        "type": kind,
        "u": owner_hash(uid),
        "kinds": ",".join(f"{k}:{n}" for k, n in sorted((counts or {}).items())),
        "at": (at or now()).isoformat(),
    }


def deliver(uid):
    """Push what changed for one student since the last push. Returns False to try again later
    (still settling, or FCM was unavailable)."""
    user = {"id": str(uid)}
    with work(user) as db:
        state = db.get(NotificationSettings, uuid.UUID(str(uid)), with_for_update=True)
        if state is None:
            return True
        tokens = list(db.scalars(select(PushDevice.token).where(PushDevice.user_id == uid)))
        events = list(
            db.execute(
                select(Activity.event_type, Activity.created_at, Activity.event_key)
                .where(Activity.user_id == uid, Activity.created_at > state.pushed_through)
                .order_by(Activity.created_at)
            ).all()
        )
        count, changed = db.execute(
            select(func.count(), func.max(Task.updated_at)).where(Task.user_id == uid)
        ).one()
        stamps = [at for _, at, _ in events]
        if changed and changed > state.pushed_through:
            stamps.append(changed)
        current = now()
        if stamps and current - max(stamps) < SETTLE and current - min(stamps) < LONGEST_WAIT:
            return False
        cursor = max([state.pushed_through, *stamps])
        prefs = preferences(state.data)
        # The student's own changes refresh the phone's reminders but are not announced.
        counts = Counter(
            kind
            for kind, _, key in events
            if prefs.push
            and kind in CATEGORIES
            and getattr(prefs, CATEGORIES[kind])
            and not key.startswith("student:")
        )
        pending_count = count
    fcm = client()
    outcomes = {}
    if fcm and tokens:
        data = message("activity" if counts else "refresh", uid, counts, cursor)
        outcomes = {token: fcm.send(token, data, urgent=bool(counts)) for token in tokens}
    with work(user) as db:
        state = db.get(NotificationSettings, uuid.UUID(str(uid)), with_for_update=True)
        invalid = [token for token, outcome in outcomes.items() if outcome == "invalid"]
        if invalid:
            for device in db.scalars(
                select(PushDevice).where(PushDevice.user_id == uid, PushDevice.token.in_(invalid))
            ):
                db.delete(device)
        if outcomes and "sent" not in outcomes.values() and "retry" in outcomes.values():
            # Keep the changes pending and back off; a later attempt sends them together.
            state.retry_at = now() + timedelta(minutes=1)
            return False
        state.pushed_through = max(state.pushed_through, cursor)
        state.task_count, state.retry_at = pending_count, None
    return True


def send_test(uid):
    fcm = client()
    if fcm is None:
        raise ApiError(503, "PUSH_CONFIGURATION", "Push notifications are not set up on this server")
    with work({"id": str(uid)}) as db:
        tokens = list(db.scalars(select(PushDevice.token).where(PushDevice.user_id == uid)))
    if not tokens:
        raise ApiError(409, "NO_DEVICE", "Open DueCare on your phone and allow notifications first")
    outcomes = [fcm.send(token, message("test", uid), urgent=True) for token in tokens]
    with work({"id": str(uid)}) as db:
        bad = [t for t, o in zip(tokens, outcomes, strict=True) if o == "invalid"]
        for device in db.scalars(
            select(PushDevice).where(PushDevice.user_id == uid, PushDevice.token.in_(bad))
        ):
            db.delete(device)
    return {"sent": outcomes.count("sent"), "failed": len(outcomes) - outcomes.count("sent")}
