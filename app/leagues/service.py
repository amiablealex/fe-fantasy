"""League operations.

Stage 6.1 holds only what the global league needs. Creation, joining, invite
codes, caps and admin actions arrive in 6.2.

`ensure_global_league` exists because migration `0006` cannot be the only
thing that creates the global league. The test suite builds its schema with
`db.create_all()` and never runs a migration, so without this the entire
visibility layer would be untestable — and a test suite that cannot exercise
the predicate is the worst possible place for that predicate to live.

Both are idempotent and safe to call on every request path that needs them.
"""
from __future__ import annotations

from sqlalchemy import select

from app.extensions import db
from app.models.league import (
    GLOBAL_INVITE_CODE,
    GLOBAL_LEAGUE_NAME,
    ROLE_MEMBER,
    League,
    LeagueMembership,
)
from app.models.user import User


def global_league() -> League | None:
    """The one league everybody is in, or None before it has been created."""
    return db.session.scalars(
        select(League).where(League.is_global.is_(True))
    ).first()


def ensure_global_league() -> League:
    """The global league, created if it is not there.

    The partial unique index means a concurrent second creation fails rather
    than producing two, which is the right outcome: this is called from
    registration and from the test fixtures, never in a hot loop.
    """
    league = global_league()
    if league is not None:
        return league
    league = League(
        name=GLOBAL_LEAGUE_NAME,
        invite_code=GLOBAL_INVITE_CODE,
        is_global=True,
    )
    db.session.add(league)
    db.session.commit()
    return league


def ensure_global_membership(user: User) -> LeagueMembership:
    """Enrol a user in the global league.

    Called at registration. A user who is already a member keeps the row they
    have, including its `hidden` flag — re-enrolling someone who has hidden
    themselves would silently undo the only privacy control they have.
    """
    league = ensure_global_league()
    membership = db.session.scalars(
        select(LeagueMembership).where(
            LeagueMembership.league_id == league.id,
            LeagueMembership.user_id == user.id,
        )
    ).first()
    if membership is not None:
        return membership

    membership = LeagueMembership(
        league_id=league.id, user_id=user.id, role=ROLE_MEMBER
    )
    db.session.add(membership)
    db.session.commit()
    return membership
