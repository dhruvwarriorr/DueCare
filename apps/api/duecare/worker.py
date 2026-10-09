"""Server-owned job execution. Browser focus and browser sessions do not drive work."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread

from sqlalchemy import text

from . import privacy, sync
from .common import owned, work
from .db import transaction
from .errors import ApiError
from .models import Connection, PrivacyJob

log = logging.getLogger("duecare.worker")


class Worker:
    def __init__(self):
        self.stop = Event()
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="duecare-job")
        self.thread = Thread(target=self.run, name="duecare-dispatch", daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
        self.pool.shutdown(wait=True, cancel_futures=True)

    def execute(self, kind, uid, job_id):
        user = {"id": str(uid)}
        try:
            if kind == "account":
                privacy.resume_account(privacy.deletion_token(job_id), True)
            elif kind == "sync":
                sync.advance(user, job_id, stop=self.stop)
            elif kind == "privacy":
                with work(user) as db:
                    job = owned(db, PrivacyJob, job_id, uid, True)
                    conn = owned(db, Connection, job.connection_id, uid, True)
                    privacy.advance_source(db, job, conn)
            elif kind == "reprocess":
                with work(user) as db:
                    conn = owned(db, Connection, job_id, uid, True)
                    if conn.data.get("reprocessRequested"):
                        result = sync.ensure_job(db, uid, conn.id, "reprocess", "manual")
                        if result["job"]["mode"] == "reprocess":
                            conn.data = {k: v for k, v in conn.data.items() if k != "reprocessRequested"}
                            conn.revision += 1
        except ApiError as exc:
            if exc.code not in (
                "SYNC_IN_PROGRESS",
                "ACCOUNT_DELETING",
                "NOT_FOUND",
                "CONNECTION_INACTIVE",
                "PRIVACY_IN_PROGRESS",
            ):
                log.warning("job deferred kind=%s code=%s", kind, exc.code)
            return False
        except Exception as exc:
            # Never log source content, credentials, or capability tokens.
            log.warning("job deferred kind=%s type=%s", kind, type(exc).__name__)
            return False
        return True

    def run(self):
        inflight, deferred = {}, {}
        last_error = 0
        while not self.stop.is_set():
            for key, future in list(inflight.items()):
                if future.done():
                    if not future.result():
                        deferred[key] = time.monotonic() + 30
                    del inflight[key]
            deferred = {key: due for key, due in deferred.items() if due > time.monotonic()}
            capacity = 4 - len(inflight)
            if capacity:
                try:
                    with transaction() as db:
                        db.execute(text("set local statement_timeout = '10s'"))
                        rows = db.execute(
                            text("select * from duecare_internal.pending_background_jobs()")
                        ).all()
                    for kind, uid, job_id in rows:
                        key = (kind, str(job_id))
                        if key in inflight or key in deferred:
                            continue
                        inflight[key] = self.pool.submit(self.execute, kind, uid, job_id)
                        capacity -= 1
                        if not capacity:
                            break
                except Exception as exc:
                    if time.monotonic() - last_error > 30:
                        log.warning("job discovery unavailable type=%s", type(exc).__name__)
                        last_error = time.monotonic()
            self.stop.wait(1)
