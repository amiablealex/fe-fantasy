"""Recording what a sync refused to apply.

The policy in SPEC.md §6: safe changes apply silently, unsafe ones roll back
that meeting untouched and record a row here. One oddity never blocks the rest
of the calendar, and nothing surprising ever applies without saying so.

Deduplication is the reason for `fingerprint`. A sync running twice a day
against an unresolved conflict would otherwise insert a fresh row every twelve
hours, and the admin page would become a wall of identical entries nobody reads.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.extensions import db
from app.models.result import SyncConflict

log = logging.getLogger(__name__)


def fingerprint(*parts: Any) -> str:
    """A stable identity for a conflict.

    Must depend only on *what* the conflict is, never on when it was noticed —
    otherwise every sync produces a new fingerprint and dedupe does nothing.
    """
    joined = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def record_conflict(
    *,
    season_id: int,
    kind: str,
    detail: dict,
    meeting_id: int | None = None,
    identity: tuple = (),
) -> SyncConflict:
    """Record a conflict, or bump the existing open one.

    `identity` is hashed into the fingerprint alongside season and kind. Pass
    the things that make this conflict *this* conflict — a meeting sequence, a
    round number — and nothing that varies run to run.
    """
    now = datetime.now(timezone.utc)
    digest = fingerprint(season_id, kind, *identity)

    existing = db.session.scalar(
        select(SyncConflict).where(
            SyncConflict.fingerprint == digest,
            SyncConflict.resolved_at.is_(None),
        )
    )
    if existing is not None:
        existing.occurrences += 1
        existing.last_seen_at = now
        existing.detail = detail
        existing.meeting_id = meeting_id
        log.warning(
            "Sync conflict %s recurred (%s times): %s", kind, existing.occurrences, detail
        )
        return existing

    conflict = SyncConflict(
        season_id=season_id,
        meeting_id=meeting_id,
        kind=kind,
        fingerprint=digest,
        detail=detail,
        first_seen_at=now,
        last_seen_at=now,
        occurrences=1,
    )
    db.session.add(conflict)
    log.warning("New sync conflict %s: %s", kind, detail)
    return conflict


def open_conflicts(season_id: int | None = None) -> list[SyncConflict]:
    stmt = select(SyncConflict).where(SyncConflict.resolved_at.is_(None))
    if season_id is not None:
        stmt = stmt.where(SyncConflict.season_id == season_id)
    return list(db.session.scalars(stmt.order_by(SyncConflict.last_seen_at.desc())))
