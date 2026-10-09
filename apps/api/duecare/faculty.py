"""Owner-specific approval for exact faculty mailboxes, separate from sender inclusion."""

import uuid

from sqlalchemy import select

from . import mail
from .models import Profile, SenderPreference, now


def entries(db, uid):
    profile = db.get(Profile, uuid.UUID(str(uid)))
    return dict((profile.data if profile else {}).get("approvedFaculty", {}))


def approved(db, uid, email):
    return bool(entries(db, uid).get(email, {}).get("approved"))


def approve(db, uid, email, origin="automatic"):
    email = mail.normalize_email(email)
    if not email or mail.academic_exclusion("", email):
        return False
    action = db.scalar(
        select(SenderPreference.action).where(
            SenderPreference.user_id == uid, SenderPreference.email == email
        )
    )
    if action == "block":
        return False
    profile = db.get(Profile, uuid.UUID(str(uid)))
    if not profile:
        return False
    current = entries(db, uid)
    if current.get(email, {}).get("approved"):
        return True
    if email in current and origin == "automatic":
        return False  # Explicit revocation remains effective until the student approves again.
    current[email] = {"approved": True, "origin": origin, "approvedAt": now().isoformat()}
    profile.data = {**profile.data, "approvedFaculty": current}
    profile.revision += 1
    return True


def revoke(db, uid, email):
    profile = db.get(Profile, uuid.UUID(str(uid)))
    if profile:
        profile.data = {
            **profile.data,
            "approvedFaculty": {
                **entries(db, uid),
                email: {"approved": False, "origin": "revoked", "revokedAt": now().isoformat()},
            },
        }
        profile.revision += 1
