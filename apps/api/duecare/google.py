"""Google source authorization and read-only Gmail/Classroom access.

Source accounts are data sources only. They never become DueCare/Supabase login identities.
Refresh and access tokens stay server-side, encrypted with versioned keys.
"""

import socket
from datetime import timedelta
from functools import lru_cache
from urllib.parse import urlencode

import google.auth.transport.requests
import google_auth_httplib2
import httplib2
import httpx
from cryptography.fernet import Fernet, InvalidToken
from google.auth import exceptions as google_auth_errors
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import settings
from .errors import ApiError
from .models import now

IDENTITY_SCOPES = ["openid", "email", "profile"]
SERVICE_SCOPES = {
    "gmail": ["https://www.googleapis.com/auth/gmail.readonly"],
    "classroom": [
        "https://www.googleapis.com/auth/classroom.courses.readonly",
        "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
        "https://www.googleapis.com/auth/classroom.announcements.readonly",
    ],
}
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"


class SourceError(Exception):
    """Normalized provider failure. Messages are sanitized and safe to show or store."""

    def __init__(self, kind, message, status=None):
        super().__init__(message)
        self.kind, self.message, self.status = kind, message, status


def callback_url():
    return settings().web_origin.rstrip("/") + "/connections/callback"


class Vault:
    """Versioned Fernet encryption for source credentials."""

    def __init__(self, spec, current):
        self.keys = {}
        for pair in filter(None, (p.strip() for p in spec.split(","))):
            version, _, key = pair.partition(":")
            try:
                self.keys[version] = Fernet(key.encode())
            except ValueError:
                raise ApiError(503, "SOURCE_CONFIGURATION", "Source connections are not configured")
        if not current or current not in self.keys:
            raise ApiError(503, "SOURCE_CONFIGURATION", "Source connections are not configured")
        self.current = current

    def encrypt(self, value):
        return self.keys[self.current].encrypt(value.encode()).decode()

    def decrypt(self, value, version):
        if version not in self.keys:
            raise SourceError("auth", "This connection's stored credentials cannot be read. Reconnect it")
        try:
            return self.keys[version].decrypt(value.encode()).decode()
        except InvalidToken:
            raise SourceError("auth", "This connection's stored credentials cannot be read. Reconnect it")


def vault():
    return Vault(settings().source_token_keys, settings().source_token_key_version)


def configured():
    s = settings()
    if not s.google_oauth_client_id or not s.google_oauth_client_secret:
        raise ApiError(503, "SOURCE_CONFIGURATION", "Gmail and Classroom connections are not configured yet")
    vault()


def _http_error(exc: HttpError):
    status = exc.resp.status if exc.resp is not None else None
    reason = ""
    try:
        reason = (
            (exc.error_details or [{}])[0].get("reason", "") if isinstance(exc.error_details, list) else ""
        )
    except (AttributeError, IndexError, TypeError):
        reason = ""
    if status == 401:
        return SourceError("auth", "Google needs you to reconnect this account", status)
    if status == 429 or (status == 403 and "ratelimit" in reason.lower()) or (status and status >= 500):
        return SourceError("retryable", "Google is temporarily unavailable. DueCare will retry", status)
    if status == 403:
        return SourceError(
            "permission", "Google did not allow this read. Check the granted permissions", status
        )
    if status == 404:
        return SourceError("not_found", "This item is no longer available from Google", status)
    return SourceError("fatal", "Google rejected this request", status)


def _call(request, access_token):
    http = google_auth_httplib2.AuthorizedHttp(
        Credentials(token=access_token), http=httplib2.Http(timeout=settings().google_request_timeout_seconds)
    )
    try:
        return request.execute(http=http, num_retries=0)
    except HttpError as exc:
        raise _http_error(exc)
    except (socket.timeout, TimeoutError, OSError, httplib2.HttpLib2Error, google_auth_errors.TransportError):
        raise SourceError("retryable", "Google could not be reached. DueCare will retry")


class GoogleSource:
    def authorization_url(self, service, state, challenge, login_hint=None):
        params = {
            "client_id": settings().google_oauth_client_id,
            "redirect_uri": callback_url(),
            "response_type": "code",
            "scope": " ".join(IDENTITY_SCOPES + SERVICE_SCOPES[service]),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent select_account",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return AUTHORIZE_URL + "?" + urlencode(params)

    def _token(self, payload):
        s = settings()
        try:
            response = httpx.post(
                TOKEN_URL,
                data={
                    **payload,
                    "client_id": s.google_oauth_client_id,
                    "client_secret": s.google_oauth_client_secret,
                },
                timeout=s.google_request_timeout_seconds,
            )
        except httpx.HTTPError:
            raise SourceError("retryable", "Google could not be reached. Try again")
        if response.status_code >= 500 or response.status_code == 429:
            raise SourceError(
                "retryable", "Google is temporarily unavailable. Try again", response.status_code
            )
        if response.status_code >= 400:
            raise SourceError("auth", "Google did not accept this authorization. Reconnect the account")
        return response.json()

    def exchange(self, code, verifier):
        return self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": callback_url(),
            }
        )

    def refresh(self, refresh_token):
        return self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def revoke(self, token):
        try:
            response = httpx.post(
                REVOKE_URL, data={"token": token}, timeout=settings().google_request_timeout_seconds
            )
        except httpx.HTTPError:
            raise SourceError("retryable", "Google could not be reached. Try disconnecting again")
        # 400 means the token is already invalid or revoked: the desired end state.
        if response.status_code >= 500 or response.status_code == 429:
            raise SourceError("retryable", "Google is temporarily unavailable. Try disconnecting again")

    def identity(self, token):
        try:
            claims = id_token.verify_oauth2_token(
                token, google.auth.transport.requests.Request(), settings().google_oauth_client_id
            )
        except (ValueError, google_auth_errors.GoogleAuthError):
            raise SourceError("auth", "Google account identity could not be verified")
        if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            raise SourceError("auth", "Google account identity could not be verified")
        return claims

    # Gmail, restricted to gmail.readonly.
    def gmail_profile(self, token):
        return _call(_gmail().getProfile(userId="me"), token)

    def gmail_list(self, token, query, page_token=None):
        return _call(
            _gmail().messages().list(userId="me", q=query, pageToken=page_token, maxResults=100), token
        )

    def gmail_history(self, token, start, page_token=None):
        request = (
            _gmail()
            .history()
            .list(userId="me", startHistoryId=start, pageToken=page_token, historyTypes=["messageAdded"])
        )
        return _call(request, token)

    def gmail_metadata(self, token, message_id):
        request = (
            _gmail()
            .messages()
            .get(userId="me", id=message_id, format="metadata", metadataHeaders=["From", "Subject", "Date"])
        )
        return _call(request, token)

    def gmail_raw(self, token, message_id):
        return _call(_gmail().messages().get(userId="me", id=message_id, format="raw"), token)

    # Classroom, restricted to courses, own coursework/submissions and announcements.
    def classroom_courses(self, token, page_token=None):
        return _call(_classroom().list(studentId="me", pageToken=page_token, pageSize=100), token)

    def classroom_coursework(self, token, course_id, page_token=None):
        request = (
            _classroom()
            .courseWork()
            .list(courseId=course_id, orderBy="updateTime desc", pageToken=page_token, pageSize=50)
        )
        return _call(request, token)

    def classroom_announcements(self, token, course_id, page_token=None):
        request = (
            _classroom()
            .announcements()
            .list(courseId=course_id, orderBy="updateTime desc", pageToken=page_token, pageSize=50)
        )
        return _call(request, token)

    def classroom_submissions(self, token, course_id, page_token=None):
        request = (
            _classroom()
            .courseWork()
            .studentSubmissions()
            .list(courseId=course_id, courseWorkId="-", userId="me", pageToken=page_token, pageSize=100)
        )
        return _call(request, token)


def _gmail():
    return _service("gmail", "v1").users()


def _classroom():
    return _service("classroom", "v1").courses()


@lru_cache
def _service(name, version):
    # Bundled static discovery documents; credentials are supplied per request at execution.
    return build(name, version, http=httplib2.Http(), static_discovery=True, cache_discovery=False)


provider = GoogleSource()


def expiry(token_response):
    return now() + timedelta(seconds=max(int(token_response.get("expires_in", 0)) - 60, 0))
