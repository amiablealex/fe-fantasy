"""What the admin health page reads.

Read-only, and every figure on the page comes from here rather than from the
template — so the judgements ("is the worker alive", "is the budget over") are
testable rather than being an expression buried in Jinja.

Nothing here is expensive. The largest query is a count over `rounds`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import and_, case, func, select

from app.extensions import db
from app.ingest.status import awaiting_results, next_session_start, stale_sessions
from app.models.calendar import Round, Season, Session
from app.models.result import SyncConflict
from app.models.worker import JOB_POLL, JOB_SEASON_SYNC, WorkerRun


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ago(when: datetime | None, now: datetime | None = None) -> str | None:
    """A duration in the largest unit that still says something useful.

    "3 days ago" rather than "4,317 minutes ago". Nobody reading this page
    needs minute precision on something that happened last week, and a page
    full of six-digit figures is harder to scan than one with words in it.
    """
    if when is None:
        return None
    now = now or _utcnow()
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    seconds = int((now - when).total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 90:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


# -----------------------------------------------------------------------------
# Sections
# -----------------------------------------------------------------------------


@dataclass
class Budget:
    used: int
    ceiling: int

    @property
    def remaining(self) -> int:
        return max(self.ceiling - self.used, 0)

    @property
    def is_over(self) -> bool:
        return self.used >= self.ceiling

    @property
    def percent(self) -> int:
        return round(100 * self.used / self.ceiling) if self.ceiling else 0


@dataclass
class WorkerState:
    last_poll: WorkerRun | None
    last_sync: WorkerRun | None
    last_any: WorkerRun | None
    unfinished: int
    silence_limit_minutes: int
    now: datetime

    @property
    def has_ever_run(self) -> bool:
        return self.last_any is not None

    @property
    def is_silent(self) -> bool:
        """No run at all for twice the heartbeat interval.

        The heartbeat exists so this question has an answer on a quiet day: a
        worker that died in October and one idling correctly through the summer
        break otherwise look identical, both showing a last run from whenever
        something last happened.
        """
        if self.last_any is None:
            return True
        limit = timedelta(minutes=self.silence_limit_minutes)
        return self.now - self.last_any.started_at > limit

    def since(self, run: WorkerRun | None) -> str | None:
        return ago(run.started_at, self.now) if run else None


@dataclass
class SeasonScoring:
    year: int
    display_name: str
    rounds: int
    scored: int
    provisional: int

    @property
    def unscored(self) -> int:
        return self.rounds - self.scored

    @property
    def is_complete(self) -> bool:
        return self.rounds > 0 and self.scored == self.rounds and not self.provisional


@dataclass
class Health:
    now: datetime
    budget: Budget
    worker: WorkerState
    awaiting: int
    stale: list[Session]
    next_session: datetime | None
    seasons: list[SeasonScoring]
    conflicts: list[SyncConflict]
    runs: list[WorkerRun] = field(default_factory=list)

    @property
    def next_session_in(self) -> str | None:
        if self.next_session is None:
            return None
        hours = int((self.next_session - self.now).total_seconds() // 3600)
        if hours < 48:
            return f"in {hours}h"
        return f"in {hours // 24}d"

    @property
    def needs_attention(self) -> bool:
        return bool(
            self.worker.is_silent
            or self.budget.is_over
            or self.stale
            or self.conflicts
        )


# -----------------------------------------------------------------------------
# Assembly
# -----------------------------------------------------------------------------


def _last_run(job: str | None = None) -> WorkerRun | None:
    stmt = select(WorkerRun).order_by(WorkerRun.started_at.desc()).limit(1)
    if job is not None:
        stmt = stmt.where(WorkerRun.job == job)
    return db.session.scalars(stmt).first()


def _season_scoring() -> list[SeasonScoring]:
    stmt = (
        select(
            Season.year,
            Season.display_name,
            func.count(Round.id),
            func.count(Round.scored_at),
            func.sum(
                case(
                    (
                        and_(
                            Round.scored_at.isnot(None),
                            Round.scoring_provisional.is_(True),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
        )
        .join(Round, Round.season_id == Season.id)
        .group_by(Season.year, Season.display_name)
        .order_by(Season.year.desc())
    )
    return [
        SeasonScoring(
            year=year,
            display_name=name,
            rounds=rounds or 0,
            scored=scored or 0,
            provisional=int(provisional or 0),
        )
        for year, name, rounds, scored, provisional in db.session.execute(stmt)
    ]


def snapshot(now: datetime | None = None, *, runs: int = 12) -> Health:
    now = now or _utcnow()
    config = current_app.config

    return Health(
        now=now,
        budget=Budget(
            used=WorkerRun.api_calls_this_month(now),
            ceiling=config["OCB_MONTHLY_CALL_CEILING"],
        ),
        worker=WorkerState(
            last_poll=WorkerRun.last_successful(JOB_POLL),
            last_sync=WorkerRun.last_successful(JOB_SEASON_SYNC),
            last_any=_last_run(),
            unfinished=db.session.scalar(
                select(func.count())
                .select_from(WorkerRun)
                .where(WorkerRun.finished_at.is_(None))
            ) or 0,
            silence_limit_minutes=config["WORKER_HEARTBEAT_MINUTES"] * 2,
            now=now,
        ),
        awaiting=awaiting_results(now),
        stale=stale_sessions(now),
        next_session=next_session_start(now),
        seasons=_season_scoring(),
        conflicts=list(db.session.scalars(
            select(SyncConflict)
            .where(SyncConflict.resolved_at.is_(None))
            .order_by(SyncConflict.last_seen_at.desc())
        )),
        runs=list(db.session.scalars(
            select(WorkerRun).order_by(WorkerRun.started_at.desc()).limit(runs)
        )),
    )
