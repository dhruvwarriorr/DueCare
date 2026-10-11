"""Notification choices and the phones that receive push notifications."""

import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import Field
from sqlalchemy import func, select

from . import push
from .common import User, revision, work
from .models import NotificationSettings, PushDevice, Task, now
from .schemas import Input

router = APIRouter(prefix="/api/v1")


class SettingsInput(Input):
    revision: int | None = Field(None, ge=1)
    settings: push.Preferences


class DeviceInput(Input):
    token: str = Field(min_length=20, max_length=4096)
    platform: Literal["android"] = "android"


class TokenInput(Input):
    token: str = Field(min_length=1, max_length=4096)


def state_for(db, uid):
    """The student's notification row, created on first use. Earlier activity is never pushed."""
    state = db.get(NotificationSettings, uuid.UUID(uid), with_for_update=True)
    if state is None:
        state = NotificationSettings(
            user_id=uuid.UUID(uid),
            data={},
            pushed_through=now(),
            task_count=db.scalar(select(func.count()).select_from(Task).where(Task.user_id == uid)) or 0,
        )
        db.add(state)
        db.flush()
    return state


def settings_out(db, state, uid):
    return {
        "revision": state.revision if state else None,
        "settings": push.preferences(state.data if state else {}).model_dump(by_alias=True),
        "push": {
            "configured": push.configured(),
            "devices": db.scalar(
                select(func.count()).select_from(PushDevice).where(PushDevice.user_id == uid)
            ),
        },
    }


@router.get("/notification-settings")
def get_settings(user=User):
    with work(user) as db:
        return settings_out(db, db.get(NotificationSettings, uuid.UUID(user["id"])), user["id"])


@router.put("/notification-settings")
def put_settings(body: SettingsInput, user=User):
    with work(user) as db:
        existing = db.get(NotificationSettings, uuid.UUID(user["id"]), with_for_update=True)
        if existing is not None:
            revision(existing, body.revision)
        state = existing or state_for(db, user["id"])
        state.data = body.settings.model_dump(by_alias=True)
        state.revision += 1 if existing is not None else 0
        db.flush()
        return settings_out(db, state, user["id"])


@router.post("/devices")
def register_device(body: DeviceInput, user=User):
    """Called on each app start; refreshing an existing token only updates when it was seen."""
    with work(user) as db:
        state_for(db, user["id"])
        device = db.scalar(
            select(PushDevice).where(PushDevice.user_id == user["id"], PushDevice.token == body.token)
        )
        if device is None:
            db.add(PushDevice(user_id=uuid.UUID(user["id"]), token=body.token, platform=body.platform))
        else:
            device.last_seen_at = now()
        return {"ok": True, "configured": push.configured()}


@router.post("/devices/unregister")
def unregister_device(body: TokenInput, user=User):
    with work(user) as db:
        for device in db.scalars(
            select(PushDevice).where(PushDevice.user_id == user["id"], PushDevice.token == body.token)
        ):
            db.delete(device)
        return {"ok": True}


@router.post("/devices/test")
def test_push(user=User):
    return push.send_test(user["id"])
