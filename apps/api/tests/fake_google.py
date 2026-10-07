"""In-memory Google source provider for tests. It never contacts Google."""

import base64
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime

from duecare.google import SERVICE_SCOPES, GoogleSource, SourceError
from duecare.models import now


def eml(
    sender,
    subject,
    body,
    message_id,
    sent=None,
    html=None,
    to="student@somaiya.edu",
    attachment=None,
    received="from relay.example.test by mx.google.com",
    headers=(),
):
    msg = EmailMessage()
    for name, value in headers:
        msg[name] = value
    msg["Received"] = received
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["Date"] = format_datetime(sent or now())
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    if attachment:
        msg.add_attachment(attachment[1], maintype="application", subtype="pdf", filename=attachment[0])
    return msg.as_bytes()


class FakeGoogle(GoogleSource):
    def __init__(self):
        self.messages, self.order, self.history = {}, [], []
        self.history_id, self.history_expired = 100, False
        self.courses, self.coursework, self.announcements, self.submissions = [], {}, {}, {}
        self.page_size = 2
        self.failures, self.calls, self.revoked, self.refreshes = [], [], [], []
        self.identity_claims = {"sub": "google-sub-1", "email": "student@somaiya.edu", "email_verified": True}
        self.scopes = None
        self.omit_refresh = False
        self.on_raw = None
        self.refresh_error = None
        self.token_details = {}

    def fail(self, method, kind="retryable", times=1):
        self.failures += [(method, kind)] * times

    def _call(self, name):
        self.calls.append(name)
        for i, (method, kind) in enumerate(self.failures):
            if method == name:
                self.failures.pop(i)
                raise SourceError(kind, f"Injected {kind} failure")

    def _page(self, items, token, key):
        start = int(token or 0)
        chunk = items[start : start + self.page_size]
        out = {key: chunk}
        if start + self.page_size < len(items):
            out["nextPageToken"] = str(start + self.page_size)
        return out

    # OAuth
    def exchange(self, code, verifier):
        self._call("exchange")
        self.last_verifier = verifier
        services = ["gmail", "classroom"] if self.service == "both" else [self.service]
        scopes = self.scopes or [
            "openid",
            "email",
            "profile",
            *[s for svc in services for s in SERVICE_SCOPES[svc]],
        ]
        response = {
            "access_token": "access-" + code,
            "expires_in": 3600,
            "id_token": "id-" + code,
            "scope": " ".join(scopes),
        }
        if not self.omit_refresh:
            response["refresh_token"] = "refresh-" + code
        return response

    def identity(self, token):
        return dict(self.identity_claims)

    def token_info(self, access_token):
        self._call("token_info")
        return dict(self.token_details)

    def refresh(self, refresh_token):
        self._call("refresh")
        self.refreshes.append(refresh_token)
        if self.refresh_error:
            raise SourceError(self.refresh_error, "Injected refresh failure")
        return {"access_token": f"access-refreshed-{len(self.refreshes)}", "expires_in": 3600}

    def revoke(self, token):
        self._call("revoke")
        self.revoked.append(token)

    # Gmail
    def add_message(self, gid, raw, labels=("INBOX",), ts=None):
        self.messages[gid] = {"raw": raw, "labels": list(labels), "ts": ts or now()}
        self.order.append(gid)
        self.history_id += 1
        self.history.append(
            {
                "id": str(self.history_id),
                "messagesAdded": [{"message": {"id": gid, "labelIds": list(labels)}}],
            }
        )

    def gmail_profile(self, token):
        self._call("gmail_profile")
        return {"emailAddress": self.identity_claims["email"], "historyId": str(self.history_id)}

    def gmail_list(self, token, query, page_token=None):
        self._call("gmail_list")
        after = int(query.split("after:")[1])
        ids = [
            g
            for g in sorted(self.order, key=lambda g: self.messages[g]["ts"], reverse=True)
            if self.messages[g]["ts"].timestamp() > after
        ]
        page = self._page([{"id": g, "threadId": "t-" + g} for g in ids], page_token, "messages")
        page["resultSizeEstimate"] = len(ids)
        return page

    def gmail_history(self, token, start, page_token=None):
        self._call("gmail_history")
        if self.history_expired:
            raise SourceError("not_found", "History expired")
        entries = [h for h in self.history if int(h["id"]) > int(start)]
        page = self._page(entries, page_token, "history")
        page["historyId"] = str(self.history_id)
        return page

    def _message(self, gid):
        if gid not in self.messages:
            raise SourceError("not_found", "Missing message")
        return self.messages[gid]

    def gmail_metadata(self, token, message_id):
        self._call("gmail_metadata")
        m = self._message(message_id)
        parsed = BytesParser(policy=policy.default).parsebytes(m["raw"], headersonly=True)
        headers = [{"name": n, "value": str(parsed[n])} for n in ("From", "Subject", "Date") if parsed[n]]
        return {
            "id": message_id,
            "threadId": "t-" + message_id,
            "labelIds": m["labels"],
            "internalDate": str(int(m["ts"].timestamp() * 1000)),
            "payload": {"headers": headers},
        }

    def gmail_raw(self, token, message_id):
        self._call("gmail_raw:" + message_id)
        m = self._message(message_id)
        if self.on_raw:
            self.on_raw(message_id)
        return {"id": message_id, "raw": base64.urlsafe_b64encode(m["raw"]).decode().rstrip("=")}

    # Classroom
    def classroom_courses(self, token, page_token=None):
        self._call("classroom_courses")
        return self._page(self.courses, page_token, "courses")

    def _course(self, course_id):
        if not any(c["id"] == course_id for c in self.courses):
            raise SourceError("not_found", "Missing course")

    def classroom_coursework(self, token, course_id, page_token=None):
        self._call("coursework:" + course_id)
        self._course(course_id)
        items = sorted(self.coursework.get(course_id, []), key=lambda w: w["updateTime"], reverse=True)
        return self._page(items, page_token, "courseWork")

    def classroom_announcements(self, token, course_id, page_token=None):
        self._call("announcements:" + course_id)
        self._course(course_id)
        items = sorted(self.announcements.get(course_id, []), key=lambda w: w["updateTime"], reverse=True)
        return self._page(items, page_token, "announcements")

    def classroom_submissions(self, token, course_id, page_token=None):
        self._call("submissions:" + course_id)
        self._course(course_id)
        return self._page(self.submissions.get(course_id, []), page_token, "studentSubmissions")

    def classroom_coursework_item(self, token, course_id, item_id):
        self._call("coursework_item:" + item_id)
        self._course(course_id)
        for item in self.coursework.get(course_id, []):
            if item["id"] == item_id:
                return item
        raise SourceError("not_found", "Missing coursework")

    def classroom_announcement_item(self, token, course_id, item_id):
        self._call("announcement_item:" + item_id)
        self._course(course_id)
        for item in self.announcements.get(course_id, []):
            if item["id"] == item_id:
                return item
        raise SourceError("not_found", "Missing announcement")
