"""What the worker actually does.

Both jobs are plain functions over an app context. Nothing here knows about
APScheduler, so the whole surface is testable — and runnable by hand from the
CLI, which is how it gets exercised before December.

The poll is database-first
--------------------------
Every tick opens with a query that costs nothing: is there a session whose
scheduled end has passed and whose results are not in? Off-season the answer is
no and the tick spends nothing at all. That is the whole of "how does the
poller stay quiet" — not a calendar of windows to maintain, just a question the
schedule already answers.

Inside a weekend, a due session is fetched speculatively (see
`app.ingest.results.sync_session_results`): one call, rather than the five that
checking the session's status first would cost.

Cadence is derived from the schedule, not counted
-------------------------------------------------
How hard to try is a function of how long ago the session was due to end, which
is stored. So there is no attempt counter to persist and nothing to rebuild
after a restart:

    < grace              too early; results are never up instantly
    grace .. eager       every tick
    eager .. give up     every patient interval
    > give up            stopped, and reported as stale

`_last_attempt` holds the patient-phase timing in memory only. A restart costs
one extra fetch, which is the right trade against a column and a migration.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from flask import current_app

from app.extensions import db
from app.ingest.results import ResultsReport, sync_session_results
from app.meetings.scoring import score_season
from app.models.calendar import Season, Session
from app.models.worker import JOB_POLL, JOB_SEASON_SYNC, WorkerRun
# The session-window queries live in `app/ingest/status.py` because the admin
# health page asks the same questions. The worker may import from the
# application; the application may not import the worker, so the shared
# definition has to sit on that side of the line.
from app.ingest.status import due_sessions, next_session_start, stale_sessions
from worker.runs import Run, budget

log = logging.getLogger(__name__)

# Session id -> when we last asked. In process only; see the module docstring.
_last_attempt: dict[int, datetime] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def target_season_year(now: datetime | None = None) -> int:
    """The ending year of the season the worker should be tracking.

    A Formula E season runs December to July and is keyed by the year it
    **ends** (SPEC.md §6), so from August onward the season of interest is next
    year's. In August 2026 that is 2027 — Season 13 — months before it appears
    in `/seasons`, which is exactly what makes the sync job pick the new season
    up on its own rather than waiting to be told.
    """
    now = now or _utcnow()
    return now.year + 1 if now.month >= 8 else now.year


# -----------------------------------------------------------------------------
# Finding work, at no cost
# -----------------------------------------------------------------------------


def _should_attempt(session_row: Session, now: datetime) -> bool:
    config = current_app.config
    eager = timedelta(minutes=config["POLL_EAGER_MINUTES"])
    patient = timedelta(minutes=config["POLL_PATIENT_INTERVAL_MINUTES"])

    ended = session_row.end_time or session_row.start_time
    if now - ended <= eager:
        return True

    last = _last_attempt.get(session_row.id)
    return last is None or now - last >= patient


# -----------------------------------------------------------------------------
# The poll
# -----------------------------------------------------------------------------


@dataclass
class PollOutcome:
    attempted: int = 0
    ingested: int = 0
    not_ready: int = 0
    stale: int = 0
    rounds_scored: int = 0
    errors: list[str] = field(default_factory=list)
    skipped_reason: str | None = None

    @property
    def did_work(self) -> bool:
        return bool(self.attempted or self.rounds_scored or self.errors)

    def summary(self) -> str:
        if self.skipped_reason:
            return f"skipped: {self.skipped_reason}"
        return (
            f"{self.attempted} attempted, {self.ingested} ingested, "
            f"{self.not_ready} not ready, {self.rounds_scored} rounds scored, "
            f"{len(self.errors)} errors"
        )

    def as_detail(self) -> dict:
        return {
            "attempted": self.attempted,
            "ingested": self.ingested,
            "not_ready": self.not_ready,
            "stale": self.stale,
            "rounds_scored": self.rounds_scored,
            "errors": self.errors[:10],
        }


def poll_once(provider, now: datetime | None = None) -> PollOutcome:
    """One tick. Returns without spending anything when there is nothing due."""
    now = now or _utcnow()
    outcome = PollOutcome()

    due = [s for s in due_sessions(now) if _should_attempt(s, now)]
    outcome.stale = len(stale_sessions(now))

    if not due:
        return outcome

    spend = budget()
    if spend.exhausted:
        outcome.skipped_reason = f"monthly call ceiling reached ({spend})"
        log.warning("Poll skipped: %s", outcome.skipped_reason)
        return outcome

    report = ResultsReport(season_year=0)
    seasons: set[int] = set()

    for session_row in due:
        _last_attempt[session_row.id] = now
        outcome.attempted += 1
        before = report.rows_created
        sync_session_results(
            provider,
            session_row,
            session_row.round.season,
            report,
            speculative=True,
        )
        if report.rows_created > before:
            seasons.add(session_row.round.season_id)

    outcome.ingested = report.sessions_fetched - report.sessions_not_ready
    outcome.not_ready = report.sessions_not_ready
    outcome.errors = list(report.errors)

    for warning in report.warnings:
        log.warning("Ingest: %s", warning)

    # Score only what just moved. `score_season` skips rounds whose results
    # have not changed since they were scored, so this stays cheap even when a
    # whole season is in the table.
    for season_id in seasons:
        season = db.session.get(Season, season_id)
        result = score_season(season)
        outcome.rounds_scored += result.rounds_scored
        outcome.errors.extend(result.errors)

    return outcome


def run_poll(provider, now: datetime | None = None) -> PollOutcome:
    """`poll_once`, recorded — but only when it did something.

    A tick that finds nothing writes no row. Liveness is the heartbeat's job,
    not this one's.
    """
    now = now or _utcnow()
    before = provider.calls if provider else 0
    outcome = poll_once(provider, now)
    if not outcome.did_work and not outcome.skipped_reason:
        return outcome

    with Run(JOB_POLL, provider=provider, calls_before=before) as run:
        run.summary = outcome.summary()
        run.detail = outcome.as_detail()
    return outcome


# -----------------------------------------------------------------------------
# The sync
# -----------------------------------------------------------------------------


def sync_is_due(now: datetime | None = None) -> bool:
    """Whether the calendar is worth refreshing.

    Two tiers, both derived from stored state. Normally daily; every few hours
    when a session starts soon, because that is when a schedule change actually
    costs someone something — a deadline that moved is a lineup nobody could
    set.
    """
    now = now or _utcnow()
    config = current_app.config

    upcoming = next_session_start(now)
    busy = upcoming is not None and upcoming - now <= timedelta(
        hours=config["SEASON_SYNC_BUSY_LEAD_HOURS"]
    )
    interval = timedelta(hours=(
        config["SEASON_SYNC_BUSY_INTERVAL_HOURS"] if busy
        else config["SEASON_SYNC_INTERVAL_HOURS"]
    ))

    last = WorkerRun.last_successful(JOB_SEASON_SYNC)
    return last is None or now - last.started_at >= interval


def run_sync(provider, now: datetime | None = None) -> str | None:
    """Refresh the calendar. Returns a summary, or None if nothing ran."""
    from app.ingest.season import SeasonNotPublished, sync_season

    now = now or _utcnow()
    if not sync_is_due(now):
        return None

    spend = budget()
    if spend.exhausted:
        log.warning("Sync skipped: monthly call ceiling reached (%s)", spend)
        return None

    year = target_season_year(now)

    with Run(JOB_SEASON_SYNC, provider=provider) as run:
        try:
            report = sync_season(provider, year)
        except SeasonNotPublished:
            # The normal condition for most of the year. Season 13 does not
            # exist in `/seasons` until the provider publishes it, and this job
            # asking every day is how it gets noticed the moment it does.
            run.summary = f"season {year} not published yet"
            run.detail = {"year": year, "published": False}
            log.info("Season %s not published yet", year)
            return run.summary

        run.summary = report.summary()
        run.detail = {
            "year": year,
            "warnings": report.warnings[:10],
            "conflicts": [str(c) for c in report.conflicts][:10],
        }
        if not report.ok:
            log.warning("Season sync reported problems: %s", report.summary())
        return run.summary
