"""Private, temporary upload transport for hosts with small request-body limits."""

import logging
import time
import uuid

import httpx
from pydantic import Field, model_validator

from .config import settings
from .errors import ApiError
from .schemas import Input
from .timetable_extract import MAX_FILE_BYTES, MAX_TOTAL_BYTES

BUCKET = "duecare-timetable-temp"
MIME = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


class UploadFile(Input):
    filename: str = Field(min_length=1, max_length=120)
    content_type: str
    size: int = Field(gt=0, le=MAX_FILE_BYTES)


class UploadRequest(Input):
    files: list[UploadFile] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def bounds(self):
        if any(f.content_type not in MIME for f in self.files):
            raise ValueError("Choose a PDF, PNG, JPEG or WebP file")
        if any(f.content_type == "application/pdf" for f in self.files) and len(self.files) != 1:
            raise ValueError("Upload one PDF or up to four pictures")
        if sum(f.size for f in self.files) > MAX_TOTAL_BYTES:
            raise ValueError("Uploads are limited to 20 MB in total")
        return self


class UploadedFile(Input):
    filename: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=100)


class UploadedRequest(Input):
    files: list[UploadedFile] = Field(min_length=1, max_length=4)


def client(token):
    return httpx.Client(
        base_url=settings().supabase_url.rstrip("/") + "/storage/v1/",
        headers={"apikey": settings().supabase_publishable_key, "Authorization": "Bearer " + token},
        timeout=15,
    )


def checked(response):
    if not response.is_success:
        raise ApiError(503, "UPLOAD_UNAVAILABLE", "Timetable upload is unavailable. Please try again")
    return response


def sign(body, user, token):
    uploads = []
    try:
        with client(token) as storage:
            for f in body.files:
                path = f"{user['id']}/{uuid.uuid4()}.{MIME[f.content_type]}"
                result = checked(storage.post(f"object/upload/sign/{BUCKET}/{path}", json={})).json()
                # Storage returns a relative path below /storage/v1; never accept another host.
                relative = result["url"]
                if not relative.startswith(f"/object/upload/sign/{BUCKET}/{path}?"):
                    raise ApiError(503, "UPLOAD_UNAVAILABLE", "Timetable upload is unavailable")
                uploads.append({"path": path, "url": str(storage.base_url).rstrip("/") + relative})
    except httpx.HTTPError:
        raise ApiError(503, "UPLOAD_UNAVAILABLE", "Timetable upload is unavailable. Please try again")
    return {"uploads": uploads}


def paths(body, user):
    result = []
    for f in body.files:
        # Exact generated shape prevents path traversal and cross-owner reads/deletions.
        try:
            owner, name = f.path.split("/")
            identifier, suffix = name.split(".")
            valid = (
                owner == user["id"] and str(uuid.UUID(identifier)) == identifier and suffix in MIME.values()
            )
        except ValueError:
            valid = False
        if not valid:
            raise ApiError(422, "INVALID_UPLOAD", "Choose the timetable files again")
        result.append(f.path)
    if len(set(result)) != len(result):
        raise ApiError(422, "INVALID_UPLOAD", "Choose the timetable files again")
    return result


def remove(body, user, token):
    names = paths(body, user)
    try:
        with client(token) as storage:
            checked(storage.request("DELETE", f"object/{BUCKET}", json={"prefixes": names}))
    except (httpx.HTTPError, ApiError):
        # The scheduled cleaner removes abandoned uploads, including expired sessions.
        logging.getLogger("duecare").warning("temporary timetable cleanup deferred")


def download(body, user, token):
    names = paths(body, user)
    files, total = [], 0
    deadline = time.monotonic() + 30
    try:
        with client(token) as storage:
            for f, name in zip(body.files, names, strict=True):
                if time.monotonic() > deadline:
                    raise ApiError(504, "UPLOAD_TIMEOUT", "Could not read the upload. Please try again")
                with storage.stream("GET", f"object/authenticated/{BUCKET}/{name}") as response:
                    checked(response)
                    data = bytearray()
                    for chunk in response.iter_bytes(65536):
                        if time.monotonic() > deadline:
                            raise ApiError(
                                504, "UPLOAD_TIMEOUT", "Could not read the upload. Please try again"
                            )
                        data.extend(chunk)
                        total += len(chunk)
                        if len(data) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                            raise ApiError(413, "FILE_TOO_LARGE", "Uploads are limited to 20 MB in total")
                files.append((f.filename, bytes(data)))
    except httpx.HTTPError:
        raise ApiError(503, "UPLOAD_UNAVAILABLE", "Could not read the upload. Please try again")
    finally:
        remove(body, user, token)
    return files
