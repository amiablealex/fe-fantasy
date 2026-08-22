"""Recording what the worker did, and refusing to overspend.

Every run that does something writes a `WorkerRun`. Runs that find nothing do
not, or the table would carry forty thousand rows a month saying "nothing
happened" — the exception is a heartbeat at most once an hour, so the admin
page can distinguish a quiet worker from a dead one.

The ceiling is the reason the poller can afford to be aggressive during a race
weekend. The free tier allows 7,500 requests a month and the cadence here
should spend a few hundred, but "should" is not a control. Summing
`WorkerRun.api_calls` over the calendar month is, and it is checked before any
job that would spend a call.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import current_app

from app.extensions import db
from app.models.worker import WorkerRun

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Budget:
    """Whether there is quota left, and how much has gone."""

    def __init__(self, used: int, ceiling: int):
        self.used = used
        self.ceiling = ceiling

    @property
    def remaining(self) -> int:
        return max(self.ceiling - self.used, 0)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.ceiling

    def __str__(self) -> str:
        return f"{self.used}/{self.ceiling} calls this month"


def budget() -> Budget:
    return Budget(
        used=WorkerRun.api_calls_this_month(),
        ceiling=current_app.config["OCB_MONTHLY_CALL_CEILING"],
    )


class Run:
    """Context manager recording one job execution.

    The row is written and committed on entry rather than on exit, so a worker
    that dies mid-job leaves a row with no `finished_at` — which is the only
    evidence a crash leaves behind, and why `WorkerRun.prune` never deletes
    unfinished rows.

    Exceptions are recorded and re-raised. APScheduler logs them and keeps the
    scheduler alive; swallowing them here would hide a failing job behind a row
    nobody is looking at.
    """

    def __init__(self, job: str, provider=None, calls_before: int | None = None):
        self.job = job
        self.provider = provider
        self.summary: str | None = None
        self.detail: dict = {}
        self.row_id: int | None = None
        # A job that has to know its outcome before deciding whether to record
        # at all — the poll, which writes nothing on a quiet tick — has already
        # spent its calls by the time this opens. It passes the count it took
        # before starting, rather than this reading a total that has moved.
        self._explicit_before = calls_before
        self._calls_before = 0

    def __enter__(self) -> "Run":
        row = WorkerRun(job=self.job, started_at=_utcnow())
        db.session.add(row)
        db.session.commit()
        self.row_id = row.id
        if self._explicit_before is not None:
            self._calls_before = self._explicit_before
        else:
            self._calls_before = self.provider.calls if self.provider else 0
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # The job body commits as it goes, so a failure may have left the
        # session unusable. Roll back before touching the row again.
        if exc_type is not None:
            db.session.rollback()

        calls = (self.provider.calls - self._calls_before) if self.provider else 0
        row = db.session.get(WorkerRun, self.row_id)
        if row is None:
            return False

        if exc_type is not None:
            summary = f"{exc_type.__name__}: {exc}"
        else:
            summary = self.summary

        row.finished_at = _utcnow()
        row.ok = exc_type is None
        row.api_calls = calls
        row.summary = summary[:500] if summary else None
        row.detail = self.detail or {}
        db.session.commit()

        return False


def prune(now: datetime | None = None) -> int:
    days = current_app.config["WORKER_RUN_RETENTION_DAYS"]
    removed = WorkerRun.prune(days, now=now)
    if removed:
        db.session.commit()
        log.info("Pruned %s worker runs older than %s days", removed, days)
    return removed
