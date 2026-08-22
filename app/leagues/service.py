"""League operations: create, join, leave, administer.

Everything here is a plain function over the ORM, in the same shape as
`app/lineups/service.py`: the routes are thin wrappers and the rules are not.
A refusal is a `LeagueError` carrying the sentence to show the player, so a
route never has to phrase a rule it does not own.

Three things are less obvious than they look.

**Invite codes are generated, not checked.** A SELECT that finds a code free
and an INSERT that uses it are two statements with a gap between them. The
loop below inserts inside a savepoint and lets the unique constraint arbitrate,
which has no gap.

**The member cap is enforced under a row lock.** Without it two people can pass
the count check simultaneously and both join a full league. The cap exists to
bound query cost (SPEC.md §2), so it is a config constant rather than a column:
what it protects is the database, not any particular league.

**The global league is refused, never special-cased at the call site.** It
cannot be left, renamed, rotated, joined by code, or administered. Every one of
those refusals lives in this module so a route cannot forget one.
"""
from __future__ import annotations

from flask import current_app
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.league import (
    GLOBAL_INVITE_CODE,
    GLOBAL_LEAGUE_NAME,
    ROLE_ADMIN,
    ROLE_MEMBER,
    League,
    LeagueMembership,
)
from app.models.user import User


class LeagueError(Exception):
    """A refusal, phrased for the player."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# -----------------------------------------------------------------------------
# The global league
# -----------------------------------------------------------------------------


def global_league() -> League | None:
    """The one league everybody is in, or None before it has been created."""
    return db.session.scalars(
        select(League).where(League.is_global.is_(True))
    ).first()


def ensure_global_league() -> League:
    """The global league, created if it is not there.

    Migration `0006` creates it for a real database, but the test suite builds
    its schema with `create_all()` and never runs a migration — so without this
    the visibility layer would be untestable, which is the worst possible
    property for that particular layer to have.
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
    membership = membership_of(user, league)
    if membership is not None:
        return membership

    membership = LeagueMembership(
        league_id=league.id, user_id=user.id, role=ROLE_MEMBER
    )
    db.session.add(membership)
    db.session.commit()
    return membership


def set_global_hidden(user: User, hidden: bool) -> LeagueMembership:
    """The account toggle. Hiding is a flag, never a deleted membership."""
    membership = ensure_global_membership(user)
    membership.hidden = bool(hidden)
    db.session.commit()
    return membership


def is_hidden_globally(user: User) -> bool:
    league = global_league()
    if league is None:
        return False
    membership = membership_of(user, league)
    return bool(membership and membership.hidden)


# -----------------------------------------------------------------------------
# Reading
# -----------------------------------------------------------------------------


def membership_of(user: User, league: League) -> LeagueMembership | None:
    return db.session.scalars(
        select(LeagueMembership).where(
            LeagueMembership.league_id == league.id,
            LeagueMembership.user_id == user.id,
        )
    ).first()


def user_leagues(user: User) -> list[tuple[League, LeagueMembership]]:
    """Every league a user belongs to, global first, then by name.

    Global first because it is the one that always has people in it, and a
    leagues page whose first row is empty teaches the wrong thing about the
    feature.
    """
    stmt = (
        select(League, LeagueMembership)
        .join(LeagueMembership, LeagueMembership.league_id == League.id)
        .where(LeagueMembership.user_id == user.id)
        .order_by(League.is_global.desc(), League.name)
    )
    return [(league, membership) for league, membership in db.session.execute(stmt)]


def members_of(league: League) -> list[tuple[LeagueMembership, User]]:
    """Every member, admins first, then by join date.

    Hidden members are included: this is the membership list, not the
    standings. Hiding withdraws you from being *shown* to others as a player —
    §2's visibility rule — and 6.3's table honours it. A league admin still
    needs to see who is in the league they administer.
    """
    stmt = (
        select(LeagueMembership, User)
        .join(User, User.id == LeagueMembership.user_id)
        .where(LeagueMembership.league_id == league.id)
        .order_by(LeagueMembership.role.desc(), LeagueMembership.joined_at)
    )
    return [(m, u) for m, u in db.session.execute(stmt)]


def member_count(league: League) -> int:
    return db.session.scalar(
        select(func.count())
        .select_from(LeagueMembership)
        .where(LeagueMembership.league_id == league.id)
    ) or 0


def league_by_code(code: str | None) -> League | None:
    """Resolve an invite code, normalised.

    Uppercased and stripped, because a code arrives from a text field on a
    phone as often as from a link. The global league's sentinel resolves to
    nothing: everybody is already in it, so a code for it would only ever
    produce a confusing "you are already a member".
    """
    if not code:
        return None
    normalised = code.strip().upper()
    if not normalised or normalised == GLOBAL_INVITE_CODE:
        return None
    return db.session.scalars(
        select(League).where(League.invite_code == normalised)
    ).first()


def cap() -> int:
    return current_app.config["MAX_LEAGUE_MEMBERS"]


def is_full(league: League) -> bool:
    if league.is_global:
        return False
    return member_count(league) >= cap()


# -----------------------------------------------------------------------------
# Writing
# -----------------------------------------------------------------------------


def create_league(user: User, name: str) -> League:
    """Create a league with the creator as its admin.

    The code is generated inside a savepoint per attempt. A plain
    try/except/rollback would discard the whole transaction on the first
    collision, taking any earlier work with it.
    """
    clean = (name or "").strip()
    if not clean:
        raise LeagueError("A league needs a name.")

    attempts = current_app.config["INVITE_CODE_MAX_ATTEMPTS"]
    for _ in range(attempts):
        league = League(
            name=clean,
            invite_code=League.generate_invite_code(),
            created_by_id=user.id,
        )
        try:
            with db.session.begin_nested():
                db.session.add(league)
        except IntegrityError:
            continue

        db.session.add(
            LeagueMembership(
                league_id=league.id, user_id=user.id, role=ROLE_ADMIN
            )
        )
        db.session.commit()
        return league

    db.session.rollback()
    raise LeagueError("Could not allocate an invite code. Try again.")


def join_league(user: User, league: League) -> LeagueMembership:
    """Add a user to a league, under a lock on the league row.

    The lock is what makes the cap a cap. Counting and inserting are two
    statements, and two people taking the last slot at the same moment both
    pass a count taken before either insert.
    """
    if league.is_global:
        # Not an error worth showing: everybody is already in it.
        return ensure_global_membership(user)

    existing = membership_of(user, league)
    if existing is not None:
        raise LeagueError(f"You are already in {league.name}.")

    # Re-read the row with FOR UPDATE. Everything from here to the commit is
    # serialised against another join to the same league.
    locked = db.session.get(League, league.id, with_for_update=True)
    if locked is None:
        raise LeagueError("That league no longer exists.")

    if member_count(locked) >= cap():
        raise LeagueError(f"{locked.name} is full.")

    membership = LeagueMembership(
        league_id=locked.id, user_id=user.id, role=ROLE_MEMBER
    )
    db.session.add(membership)
    try:
        db.session.commit()
    except IntegrityError:
        # The unique constraint caught a double submit. Not a failure.
        db.session.rollback()
        return membership_of(user, locked)
    return membership


def leave_league(user: User, league: League) -> None:
    """Remove a user's own membership.

    If the last admin leaves, the earliest-joined remaining member is promoted.
    A league with members and no admin has nobody who can rotate its code or
    remove anyone, and it would sit there permanently unadministrable with no
    error anywhere to explain why.
    """
    if league.is_global:
        raise LeagueError(
            "You can't leave the global league. Hide yourself from it in your "
            "account settings instead."
        )

    membership = membership_of(user, league)
    if membership is None:
        raise LeagueError("You are not in that league.")

    was_admin = membership.is_admin
    db.session.delete(membership)
    db.session.flush()

    if was_admin:
        _promote_successor(league)
    db.session.commit()


def remove_member(actor: User, league: League, target: User) -> None:
    """An admin removing someone else."""
    if league.is_global:
        raise LeagueError("The global league has no administrators.")

    actor_membership = membership_of(actor, league)
    if actor_membership is None or not actor_membership.is_admin:
        raise LeagueError("Only a league admin can remove members.")
    if target.id == actor.id:
        raise LeagueError("Leave the league instead of removing yourself.")

    target_membership = membership_of(target, league)
    if target_membership is None:
        raise LeagueError("They are not in that league.")

    was_admin = target_membership.is_admin
    db.session.delete(target_membership)
    db.session.flush()
    if was_admin:
        _promote_successor(league)
    db.session.commit()


def _promote_successor(league: League) -> None:
    """Give a league an admin if it has lost its last one and still has members."""
    remaining = db.session.scalars(
        select(LeagueMembership)
        .where(LeagueMembership.league_id == league.id)
        .order_by(LeagueMembership.joined_at)
    ).all()
    if not remaining:
        return
    if any(m.is_admin for m in remaining):
        return
    remaining[0].role = ROLE_ADMIN


def rename_league(actor: User, league: League, name: str) -> League:
    if league.is_global:
        raise LeagueError("The global league can't be renamed.")
    _require_admin(actor, league)
    clean = (name or "").strip()
    if not clean:
        raise LeagueError("A league needs a name.")
    league.name = clean
    db.session.commit()
    return league


def rotate_invite_code(actor: User, league: League) -> League:
    """Issue a new code, which is how an invite is revoked.

    There is no separate "closed" state: a rotated code makes every link
    already shared dead, which is the whole of what revocation means here.
    """
    if league.is_global:
        raise LeagueError("The global league has no invite code.")
    _require_admin(actor, league)

    attempts = current_app.config["INVITE_CODE_MAX_ATTEMPTS"]
    for _ in range(attempts):
        candidate = League.generate_invite_code()
        if candidate == league.invite_code:
            continue
        league.invite_code = candidate
        try:
            with db.session.begin_nested():
                db.session.flush()
        except IntegrityError:
            continue
        db.session.commit()
        return league

    db.session.rollback()
    raise LeagueError("Could not allocate an invite code. Try again.")


def _require_admin(actor: User, league: League) -> None:
    membership = membership_of(actor, league)
    if membership is None or not membership.is_admin:
        raise LeagueError("Only a league admin can do that.")
