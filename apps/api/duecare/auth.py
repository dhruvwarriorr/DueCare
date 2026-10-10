import base64
import hashlib
import json
import secrets
import uuid
from datetime import timedelta
from functools import lru_cache
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request
from sqlalchemy import select, text

from .config import settings
from .db import transaction
from .errors import ApiError
from .models import LoginState, WebSession, now


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def crypt():
    try:
        return Fernet(settings().session_encryption_key.encode())
    except ValueError:
        raise ApiError(503, "AUTH_CONFIGURATION", "Authentication is not configured")


def gateway(request: Request):
    configured = settings().gateway_secret
    if not configured or not secrets.compare_digest(request.headers.get("x-gateway-secret", ""), configured):
        raise ApiError(401, "GATEWAY_REQUIRED", "Use the application gateway")


@lru_cache
def jwks():
    return jwt.PyJWKClient(settings().supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json")


class SupabaseAuth:
    def exchange(self, grant, payload):
        try:
            with httpx.Client(timeout=15) as client:
                response = client.post(
                    settings().supabase_url.rstrip("/") + "/auth/v1/token",
                    params={"grant_type": grant},
                    headers={"apikey": settings().supabase_publishable_key},
                    json=payload,
                )
                if response.status_code >= 400:
                    raise ApiError(401, "SIGN_IN_REQUIRED", "Please sign in again")
                return response.json()
        except httpx.HTTPError:
            raise ApiError(503, "AUTH_UNAVAILABLE", "Sign-in is temporarily unavailable. Try again")

    def claims(self, token):
        try:
            key = jwks().get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                key,
                algorithms=["RS256", "ES256"],
                audience="authenticated",
                issuer=settings().supabase_url.rstrip("/") + "/auth/v1",
                options={"require": ["exp", "iat", "sub", "aud", "iss", "session_id"]},
            )
        except (jwt.PyJWTError, ValueError):
            raise ApiError(401, "SIGN_IN_REQUIRED", "Please sign in again")

    def identity(self, db, claims):
        try:
            user_id, session_id = uuid.UUID(claims["sub"]), uuid.UUID(claims["session_id"])
        except (ValueError, KeyError):
            raise ApiError(401, "SIGN_IN_REQUIRED", "Please sign in again")
        # Provider identity is read from auth.identities, never editable user_metadata.
        row = db.execute(
            text("select id,email,identity_data from duecare_internal.lookup_auth_identity(:uid,:sid)"),
            {"uid": user_id, "sid": session_id},
        ).first()
        if not row:
            raise ApiError(401, "SESSION_REVOKED", "Your session has ended. Please sign in again")
        identity = row.identity_data
        email = str(identity.get("email", "")).lower()
        if (
            not email.endswith("@somaiya.edu")
            or email.count("@") != 1
            or identity.get("email_verified") is not True
            or email != row.email.lower()
        ):
            raise ApiError(403, "SOMAIYA_REQUIRED", "Sign in with your verified Somaiya Google account")
        return {
            "id": str(user_id),
            "email": email,
            "name": identity.get("full_name") or identity.get("name"),
            "photo": identity.get("avatar_url") or identity.get("picture"),
        }

    def logout(self, token):
        try:
            response = httpx.post(
                settings().supabase_url.rstrip("/") + "/auth/v1/logout",
                params={"scope": "local"},
                headers={"apikey": settings().supabase_publishable_key, "authorization": "Bearer " + token},
                timeout=15,
            )
            if response.status_code not in (200, 204, 401, 403):
                raise ApiError(503, "AUTH_UNAVAILABLE", "Could not end the Google login session. Try again")
        except httpx.HTTPError:
            raise ApiError(503, "AUTH_UNAVAILABLE", "Could not end the login session. Try again")


provider = SupabaseAuth()


# Sign-in also grants read-only Gmail and Classroom access for the Somaiya account.
SOURCE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",  # Optional: teacher names on Classroom posts.
]


def login_start(consent=False):
    if not settings().supabase_url or not settings().supabase_publishable_key:
        raise ApiError(503, "AUTH_CONFIGURATION", "Google sign-in is not configured yet")
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    with transaction() as db:
        db.query(LoginState).filter(LoginState.created_at < now() - timedelta(minutes=10)).delete()
        db.add(LoginState(id=digest(state), verifier=crypt().encrypt(verifier.encode()).decode()))
        db.commit()
    url = (
        settings().supabase_url.rstrip("/")
        + "/auth/v1/authorize?"
        + urlencode(
            {
                "provider": "google",
                "redirect_to": settings().web_origin + "/auth/callback",
                "code_challenge": challenge,
                "code_challenge_method": "s256",
                "hd": "somaiya.edu",
                "scopes": " ".join(["openid", "email", "profile", *SOURCE_SCOPES]),
                # Forwarded to Google: an offline grant so syncing works between visits.
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent" if consent else "select_account",
            }
        )
    )
    return {"state": state, "url": url}


def login_finish(state, code):
    with transaction() as db:
        entry = db.scalar(select(LoginState).where(LoginState.id == digest(state)).with_for_update())
        if not entry or entry.created_at < now() - timedelta(minutes=10):
            raise ApiError(401, "LOGIN_EXPIRED", "Sign-in expired. Please try again")
        verifier = crypt().decrypt(entry.verifier.encode()).decode()
        db.delete(entry)
        db.commit()  # Consume state once, including when exchange fails.
    tokens = provider.exchange("pkce", {"auth_code": code, "code_verifier": verifier})
    claims = provider.claims(tokens["access_token"])
    with transaction() as db:
        identity = provider.identity(db, claims)
        handle = secrets.token_urlsafe(32)
        db.add(
            WebSession(
                id=digest(handle),
                user_id=uuid.UUID(identity["id"]),
                tokens=crypt()
                .encrypt(
                    json.dumps(
                        {"access_token": tokens["access_token"], "refresh_token": tokens["refresh_token"]}
                    ).encode()
                )
                .decode(),
            )
        )
        db.commit()
    # Google tokens are returned once, at this exchange; the caller stores them for source syncing.
    google_tokens = {k: tokens.get(k) for k in ("provider_token", "provider_refresh_token")}
    return handle, identity, google_tokens


def current_user(request: Request):
    gateway(request)
    handle = request.headers.get("x-session", "")
    with transaction() as db:
        # Durable row lock serializes refresh across requests, tabs and server instances.
        entry = db.scalar(select(WebSession).where(WebSession.id == digest(handle)).with_for_update())
        if not entry:
            raise ApiError(401, "SIGN_IN_REQUIRED", "Please sign in")
        try:
            tokens = json.loads(crypt().decrypt(entry.tokens.encode()))
        except InvalidToken:
            raise ApiError(401, "SIGN_IN_REQUIRED", "Your session cannot be restored. Please sign in again")
        unverified = jwt.decode(tokens["access_token"], options={"verify_signature": False})
        if float(unverified.get("exp", 0)) <= now().timestamp() + 30:
            tokens = provider.exchange("refresh_token", {"refresh_token": tokens["refresh_token"]})
            tokens = {k: tokens[k] for k in ("access_token", "refresh_token")}
            entry.tokens = crypt().encrypt(json.dumps(tokens).encode()).decode()
        identity = provider.identity(db, provider.claims(tokens["access_token"]))
        if identity["id"] != str(entry.user_id):
            raise ApiError(401, "SESSION_REVOKED", "Please sign in again")
        db.commit()
        return identity


def logout(request):
    gateway(request)
    with transaction() as db:
        entry = db.scalar(
            select(WebSession)
            .where(WebSession.id == digest(request.headers.get("x-session", "")))
            .with_for_update()
        )
        if entry:
            tokens = json.loads(crypt().decrypt(entry.tokens.encode()))
            provider.logout(tokens["access_token"])
            db.delete(entry)
        db.commit()
