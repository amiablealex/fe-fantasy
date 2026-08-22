"""Where ingestion has got to, as queries.

Three questions about the schedule, all answered without an API call:

    due       a session whose scheduled end has passed and whose results are
              not in — the poller's work list
    stale     one it has given up on
    pending   either of the above, plus the ones still inside the grace period

These live here rather than in `worker/` because the admin health page asks the
same questions the poller does, and the web application must not import the
worker — `worker/` is outside `app/` precisely so that dependency cannot form.
Two implementations of "past the give-up window" would eventually disagree, and
the one that drifted would be the one nobody was watching.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.calendar import SCORING_STAGES, Round, Session


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def scheduled_end():
    """When a session was due to finish.

    `end_time` where the provider gave one, `start_time` otherwise. A session
    with neither is invisible to the poller rather than guessed at: inventing a
    duration would mean fetching at the wrong moment and never knowing why.
    """
    return func.coalesce(Session.end_time, Session.start_time)


def _awaiting():
    return (
        select(Session)
        .join(Round, Session.round_id == Round.id)
        .options(joinedload(Session.round).joinedload(Round.season))
        .where(
            Session.stage.in_(SCORING_STAGES),
            Session.results_ingested_at.is_(None),
            scheduled_end().isnot(None),
        )
    )


def due_sessions(now: datetime | None = None) -> list[Session]:
    """Sessions worth asking about right now. Costs no API calls."""
    now = now or _utcnow()
    config = current_app.config
    grace = timedelta(minutes=config["POLL_SESSION_GRACE_MINUTES"])
    give_up = timedelta(hours=config["POLL_GIVE_UP_HOURS"])

    stmt = (
        _awaiting()
        .where(scheduled_end() <= now - grace, scheduled_end() >= now - give_up)
        .order_by(scheduled_end())
    )
    return list(db.session.scalars(stmt).unique())


def stale_sessions(now: datetime | None = None) -> list[Session]:
    """Sessions the poller gave up on.

    Worth surfacing rather than forgetting: a session that never published is a
    round that stays provisional forever, and the remedy —
    `flask backfill-results` — is manual on purpose.
    """
    now = now or _utcnow()
    give_up = timedelta(hours=current_app.config["POLL_GIVE_UP_HOURS"])
    stmt = _awaiting().where(scheduled_end() < now - give_up).order_by(scheduled_end())
    return list(db.session.scalars(stmt).unique())


def awaiting_results(now: datetime | None = None) -> int:
    """Scoring sessions with no results yet, whenever they were due."""
    now = now or _utcnow()
    return db.session.scalar(
        select(func.count()).select_from(_awaiting().subquery())
    ) or 0


def next_session_start(now: datetime | None = None) -> datetime | None:
    """When the next scheduled session begins, across every season."""
    now = now or _utcnow()
    return db.session.scalar(
        select(func.min(Session.start_time)).where(Session.start_time > now)
    )
