"""Endpoints the mobile app calls directly, without the web gateway.

Sign-in is the web flow with a different return address: the same Supabase PKCE exchange, the
same encrypted server-side session and the same Gmail/Classroom grant. Supabase returns to the
app's deep link with only a code; redeeming it also needs the one-use state, which only the app
that started sign-in holds, so another app that intercepts the link cannot sign in with it.
Afterwards the app sends the session handle as a bearer token (see auth.session_handle).
"""

from fastapi import APIRouter, Request
from pydantic import Field

from . import auth, privacy, sources_api
from .config import settings
from .errors import ApiError
from .privacy_api import ResumeInput
from .schemas import Input

router = APIRouter(prefix="/api/v1/mobile")


class StartInput(Input):
    # Re-asks Google for Gmail and Classroom access (after it was declined or revoked).
    consent: bool = False


class CallbackInput(Input):
    state: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=3000)


@router.post("/auth/start")
def start(body: StartInput | None = None):
    redirect = settings().mobile_redirect_url
    if not redirect:
        raise ApiError(503, "AUTH_CONFIGURATION", "Mobile sign-in is not configured yet")
    return auth.login_start(consent=bool(body and body.consent), redirect=redirect)


@router.post("/auth/callback")
def callback(body: CallbackInput):
    handle, identity, provider = auth.login_finish(body.state, body.code)
    sources_api.attach_login_grant(identity, provider)
    return {"session": handle}


@router.post("/auth/logout")
def logout(request: Request):
    auth.logout(request)
    return {"ok": True}


@router.post("/account-deletion")
def account_resume(body: ResumeInput):
    # The 64-character resume token is the credential: the login is gone once deletion finishes.
    return privacy.resume_account(body.token, body.advance)
