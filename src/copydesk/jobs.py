"""Background jobs: work that shouldn't happen during a web request.

Jobs are rows in the ``jobs`` table, so they're saved in the same transaction
as whatever caused them. When an article is accepted, the "you've been
accepted" email can't get lost even if the server restarts a second later.

Run jobs in one of three ways (see docs/installation.md):

* ``quillsail worker``: a long-running process (recommended; systemd examples are in the installation guide).
* ``quillsail jobs run``: process what's waiting, then exit. Run it from cron,
  like MediaWiki's runJobs.php.
* ``[jobs] run_in_web = true``: a thread inside the web server. Fine for small
  sites that can't run a second process.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from flask import Flask, current_app, g
from sqlalchemy import delete, func, select, update

from copydesk import settings
from copydesk.db import db
from copydesk.models import EmailOAuthFlow, HostingOAuthFlow, Job, RateLimit
from copydesk.utils import utcnow

log = logging.getLogger("copydesk.jobs")

HANDLERS: dict[str, Callable[[dict[str, Any]], None]] = {}

PRIORITY_URGENT = 10  # account emails people are waiting for
PRIORITY_NORMAL = 50
PRIORITY_BULK = 100  # newsletter batches

STALE_AFTER = timedelta(minutes=15)
HEARTBEAT_KEY = "system.worker_heartbeat"


class RetryLater(Exception):
    """Raise from a handler to try again later without logging a traceback."""

    def __init__(self, message: str = "", delay: int = 60) -> None:
        super().__init__(message)
        self.delay = delay


def handler(kind: str):
    def decorator(fn: Callable[[dict[str, Any]], None]):
        HANDLERS[kind] = fn
        return fn

    return decorator


def enqueue(
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    priority: int = PRIORITY_NORMAL,
    delay: int = 0,
    max_attempts: int = 5,
) -> Job:
    """Add a job to the session. It runs once the caller commits."""
    job = Job(
        kind=kind,
        payload=payload or {},
        priority=priority,
        run_at=utcnow() + timedelta(seconds=delay),
        max_attempts=max_attempts,
    )
    db.session.add(job)
    return job


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident() % 100000}"


def _claim(worker: str) -> Job | None:
    now = utcnow()
    candidates = db.session.scalars(
        select(Job.id)
        .where(Job.status == "queued", Job.run_at <= now)
        .order_by(Job.priority, Job.run_at, Job.id)
        .limit(10)
    ).all()
    for job_id in candidates:
        result = db.session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="running", locked_by=worker, locked_at=now, attempts=Job.attempts + 1)
        )
        db.session.commit()
        if result.rowcount == 1:
            return db.session.get(Job, job_id, populate_existing=True)
    return None


def _backoff(attempts: int) -> int:
    return min(3600, 30 * 2 ** max(0, attempts - 1))


def run_one(worker: str | None = None) -> bool:
    """Run the next waiting job. Returns False if there was nothing to do."""
    from copydesk.maintenance import active

    if active(current_app.extensions["copydesk"].config):
        return False
    worker = worker or worker_id()
    job = _claim(worker)
    if job is None:
        return False
    job_id, kind, payload = job.id, job.kind, dict(job.payload or {})
    settings.invalidate()
    from copydesk.app import refresh_theme

    refresh_theme(current_app._get_current_object())
    started = time.monotonic()
    g._running_job = (job_id, worker)
    try:
        fn = HANDLERS.get(kind)
        if fn is None:
            raise RuntimeError(f"No handler is registered for job type {kind!r}.")
        fn(payload)
        db.session.commit()
        db.session.execute(
            update(Job).where(Job.id == job_id, Job.status == "running", Job.locked_by == worker)
            .values(status="done", finished_at=utcnow(), last_error="", locked_by="", locked_at=None)
        )
        db.session.commit()
        log.info("Job %s (%s) finished in %.1fs", job_id, kind, time.monotonic() - started)
    except Exception as exc:  # noqa: BLE001 - every failure must be recorded
        db.session.rollback()
        retry_delay = exc.delay if isinstance(exc, RetryLater) else None
        error = str(exc) if isinstance(exc, RetryLater) else traceback.format_exc(limit=8)
        job = db.session.get(Job, job_id, populate_existing=True)
        if job is not None and job.status == "running" and job.locked_by == worker:
            job.last_error = error[-4000:]
            if job.attempts >= job.max_attempts:
                job.status = "failed"
                job.finished_at = utcnow()
                log.error("Job %s (%s) failed for good: %s", job_id, kind, exc)
            else:
                job.status = "queued"
                job.run_at = utcnow() + timedelta(seconds=retry_delay or _backoff(job.attempts))
                log.warning("Job %s (%s) failed, will retry: %s", job_id, kind, exc)
            job.locked_by = ""
            job.locked_at = None
            db.session.commit()
    finally:
        g.pop("_running_job", None)
        db.session.remove()
    return True


def renew_lease() -> None:
    """Keep a long-running handler claimed. The caller commits its progress."""
    running = g.get("_running_job")
    if running is None:
        return
    job_id, worker = running
    result = db.session.execute(
        update(Job).where(Job.id == job_id, Job.status == "running", Job.locked_by == worker)
        .values(locked_at=utcnow())
    )
    if result.rowcount != 1:
        raise RuntimeError("This worker no longer owns the job.")
    settings.set_value(HEARTBEAT_KEY, utcnow().isoformat(timespec="seconds"))


def maintenance() -> None:
    """Housekeeping that runs every so often: recover stuck jobs, start scheduled issues."""
    from copydesk import newsletter
    from copydesk.maintenance import active

    if active(current_app.extensions["copydesk"].config):
        return

    settings.invalidate()
    now = utcnow()
    db.session.execute(
        update(Job)
        .where(Job.status == "running", Job.locked_at < now - STALE_AFTER)
        .values(status="queued", locked_by="", locked_at=None)
    )
    db.session.execute(delete(Job).where(Job.status == "done", Job.finished_at < now - timedelta(days=14)))
    db.session.execute(delete(HostingOAuthFlow).where(HostingOAuthFlow.created_at < now - timedelta(minutes=10)))
    db.session.execute(delete(EmailOAuthFlow).where(EmailOAuthFlow.created_at < now - timedelta(minutes=10)))
    db.session.execute(delete(RateLimit).where(RateLimit.window_start < now - timedelta(days=1)))
    db.session.commit()
    if settings.get("hosting.edge") and not db.session.scalar(select(Job.id).where(Job.kind == "edge.replay", Job.status.in_(("queued", "running"))).limit(1)):
        enqueue("edge.replay")
    if settings.get("hosting.edge"):
        from copydesk import edge

        edge.schedule_snapshot()
    newsletter.start_due_issues()
    db.session.commit()
    from copydesk.jekyll_import import remove_stale_imports

    remove_stale_imports()


def heartbeat() -> None:
    settings.set_value(HEARTBEAT_KEY, utcnow().isoformat(timespec="seconds"))
    settings.set_value("system.worker_identity", worker_id())
    db.session.commit()


def run_pending(max_jobs: int | None = None, max_seconds: float | None = None) -> int:
    """Run maintenance, then jobs until the queue is empty or a limit is reached."""
    started = time.monotonic()
    maintenance()
    heartbeat()
    count = 0
    worker = worker_id()
    while max_jobs is None or count < max_jobs:
        if max_seconds is not None and time.monotonic() - started >= max_seconds:
            break
        if not run_one(worker):
            break
        count += 1
    return count


def queue_counts() -> dict[str, int]:
    rows = db.session.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    return dict(rows)


class Worker:
    """The long-running loop behind ``quillsail worker``."""

    def __init__(self, app: Flask, poll_interval: float = 2.0, maintenance_interval: float = 30.0) -> None:
        self.app = app
        self.poll_interval = poll_interval
        self.maintenance_interval = maintenance_interval
        self.stop = threading.Event()

    def install_signal_handlers(self) -> None:
        def _stop(signum, _frame):
            log.info("Received signal %s; finishing the current job, then stopping.", signum)
            self.stop.set()

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

    def run(self) -> None:
        worker = worker_id()
        last_maintenance = 0.0
        log.info("Worker %s started.", worker)
        with self.app.app_context():
            while not self.stop.is_set():
                try:
                    if time.monotonic() - last_maintenance >= self.maintenance_interval:
                        maintenance()
                        heartbeat()
                        last_maintenance = time.monotonic()
                    if not run_one(worker):
                        self.stop.wait(self.poll_interval)
                except Exception:  # noqa: BLE001 - keep the worker alive
                    log.exception("Worker loop error; retrying shortly.")
                    db.session.rollback()
                    self.stop.wait(max(self.poll_interval, 5))
                finally:
                    db.session.remove()
        log.info("Worker %s stopped.", worker)


def start_background_worker(app: Flask) -> threading.Thread:
    """Run a worker in a daemon thread of this process (``run_in_web`` and ``quillsail serve``)."""
    existing = app.extensions.get("copydesk_worker_thread")
    if existing is not None and existing.is_alive():
        return existing
    worker = Worker(app)
    thread = threading.Thread(target=worker.run, name="copydesk-worker", daemon=True)
    app.extensions["copydesk_worker_thread"] = thread
    thread.start()
    return thread


def worker_last_seen() -> datetime | None:
    value = settings.get(HEARTBEAT_KEY, None)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def mail_config():
    from copydesk.email_connections import effective_mail_config

    return effective_mail_config()
