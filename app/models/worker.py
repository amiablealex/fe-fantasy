"""WorkerRun — one row per background job execution.

Two jobs in one table, deliberately.

The first is diagnostic: SPEC.md §10 wants the admin surface to show last
successful poll and sync health, and a log line on Railway is not a thing a
page can read.

The second is the reason it is not optional. The provider's free tier allows
7,500 requests a month and the poller is written to be aggressive inside a race
weekend, which is only safe if something can say no. `api_calls_this_month`
is that something: one indexed aggregate, checked before any fetch phase
begins. Without a table there is nowhere for a monthly count to live, because
the worker restarts and an in-process counter restarts with it.

Rows are pruned by age rather than kept forever. A poll every ninety seconds
through a race weekend is a few thousand rows a season, and none of them is
interesting a month later.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

JOB_POLL = "poll"
JOB_SEASON_SYNC = "season_sync"
JOB_SCORE = "score"
JOBS = (JOB_POLL, JOB_SEASON_SYNC, JOB_SCORE)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkerRun(db.Model):
    __tablename__ = "worker_runs"
    __table_args__ = (
        # "The last successful poll" and "this job's recent history" are the
        # only two questions asked of this table, and both are this index.
        Index("ix_worker_runs_job_started", "job", "started_at"),
        Index("ix_worker_runs_started", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(32), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    # Null while running. A row with no finish that is hours old is a crashed
    # worker, which is worth being able to see.
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool | None] = mapped_column(Boolean)

    # HTTP attempts made during this run, retries included. Summed over the
    # calendar month, this is what the ceiling checks.
    api_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    summary: Mapped[str | None] = mapped_column(String(500))
    # Free-form per job, same pattern as SyncConflict.detail: sessions fetched,
    # rounds scored, conflicts raised. Rendered as key-value pairs, not parsed.
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    @property
    def is_running(self) -> bool:
        return self.finished_at is None

    @property
    def duration_seconds(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    # ----- queries -----

    @classmethod
    def api_calls_this_month(cls, now: datetime | None = None) -> int:
        """Requests spent since the first of the current UTC month.

        Calendar month, matching how the provider's quota is described. Whether
        their window is actually a calendar month is unknown; assuming the
        stricter reading costs nothing at under ten percent of the allowance.
        """
        now = now or _utcnow()
        start = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
        )
        total = db.session.scalar(
            select(func.coalesce(func.sum(cls.api_calls), 0)).where(
                cls.started_at >= start
            )
        )
        return int(total or 0)

    @classmethod
    def last_successful(cls, job: str) -> "WorkerRun | None":
        return db.session.scalars(
            select(cls)
            .where(cls.job == job, cls.ok.is_(True))
            .order_by(cls.started_at.desc())
            .limit(1)
        ).first()

    @classmethod
    def prune(cls, older_than_days: int, now: datetime | None = None) -> int:
        """Drop finished runs past the retention window.

        Never touches unfinished rows: an ancient row with no `finished_at` is
        the evidence of a crash, and deleting the evidence on a schedule is how
        an intermittent failure stays invisible.
        """
        cutoff = (now or _utcnow()) - timedelta(days=older_than_days)
        result = db.session.execute(
            delete(cls).where(cls.started_at < cutoff, cls.finished_at.isnot(None))
        )
        return result.rowcount or 0

    def __repr__(self) -> str:  # pragma: no cover
        state = "running" if self.is_running else ("ok" if self.ok else "failed")
        return f"<WorkerRun {self.job} {state} calls={self.api_calls}>"
