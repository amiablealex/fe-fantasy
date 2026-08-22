"""Who may see whose lineup.

SPEC.md §2 states the rule as one sentence — a lineup is hidden until its
meeting's deadline passes, then visible to co-members of the viewer's leagues —
and requires it to be enforced in the query layer rather than in a template,
because a check that lives only in Jinja leaks through the first JSON endpoint
or HTMX partial anyone adds.

That is enforced here by a structural rule rather than by discipline: **no
function in this codebase returns another user's lineup without a viewer
argument.** `app/lineups/service.py` reads the signed-in player's own lineups
and takes a `user`; everything foreign comes through this module and takes a
`viewer` and a `subject`. A route that wants someone else's picks has nowhere
else to get them.

The sentence is two independent predicates and they are kept separate:

    locked_clause        the meeting's deadline has passed
    shared_league_clause the viewer and the subject share a league, and the
                         subject is not hidden in it

Both are required. Neither is sufficient. The global league makes the second
true for almost everyone, which is a fact about the data rather than a second
code path — there is no `is_global` anywhere in this file.

**The null-deadline trap.** `Meeting.deadline_at` is nullable: an unsynced
meeting has no deadline yet. A null deadline means *not locked*, matching
`grace_meeting` in the lineup service, so an unsynced weekend is private. In
SQL this falls out of three-valued logic — `NULL <= now` is NULL and the row
does not match — but the Python spelling people reach for
(`if not m.deadline_at or m.deadline_at <= now`) inverts it, and the naive
comparison raises TypeError. Both cases are pinned by tests.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, literal, or_, select
from sqlalchemy.orm import aliased

from app.extensions import db
from app.models.calendar import Meeting, Season
from app.models.league import League, LeagueMembership
from app.models.lineup import LineupSnapshot
from app.models.user import User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# -----------------------------------------------------------------------------
# The two clauses
# -----------------------------------------------------------------------------


def locked_clause(now: datetime):
    """Meetings whose deadline has passed.

    The explicit null test is redundant in SQL and present anyway, because it
    is the line a reader checks when asking whether an unsynced meeting leaks.
    """
    return and_(Meeting.deadline_at.is_not(None), Meeting.deadline_at <= now)


def shared_league_clause(viewer_id, subject_id):
    """An EXISTS: viewer and subject share a league where subject is shown.

    `subject_id` may be a literal or a column, so the same clause serves "can
    this one person be seen" and "which of these people can be seen" without a
    second implementation.

    The viewer's own `hidden` flag is deliberately not tested. Hiding withdraws
    your visibility to others; it does not withdraw your sight of them.
    """
    viewer_m = aliased(LeagueMembership)
    subject_m = aliased(LeagueMembership)
    return (
        select(literal(1))
        .select_from(viewer_m)
        .join(subject_m, subject_m.league_id == viewer_m.league_id)
        .where(
            viewer_m.user_id == viewer_id,
            subject_m.user_id == subject_id,
            subject_m.hidden.is_(False),
        )
        .exists()
    )


# -----------------------------------------------------------------------------
# People
# -----------------------------------------------------------------------------


def can_view(viewer, subject) -> bool:
    """Whether `viewer` may see `subject`'s locked lineups at all.

    A user can always see themselves, hidden or not — the flag is about being
    shown to others. The deadline gate still applies to them here, because the
    only screens that read through this module are the ones that show a lineup
    in a shared context. The editor reads the open weekend through
    `lineups.service`, which is the module that is allowed to.
    """
    if viewer is None or subject is None:
        return False
    if not getattr(viewer, "is_authenticated", True):
        return False
    if viewer.id == subject.id:
        return True
    return bool(
        db.session.scalar(select(shared_league_clause(viewer.id, subject.id)))
    )


def visible_user(viewer, user_id) -> User | None:
    """Load a user only if the viewer may see them.

    Returns None both for "no such account" and "not visible to you", so a
    route built on this answers 404 in both cases. A 403 would confirm the
    account exists.
    """
    subject = db.session.get(User, user_id)
    if subject is None or not can_view(viewer, subject):
        return None
    return subject


def shared_leagues(viewer, subject) -> list[League]:
    """The leagues through which these two can see each other.

    For a profile header: naming the connection is the difference between
    "some stranger's picks" and "your league".
    """
    if viewer is None or subject is None or viewer.id == subject.id:
        return []
    viewer_m = aliased(LeagueMembership)
    subject_m = aliased(LeagueMembership)
    stmt = (
        select(League)
        .join(viewer_m, viewer_m.league_id == League.id)
        .join(subject_m, subject_m.league_id == League.id)
        .where(
            viewer_m.user_id == viewer.id,
            subject_m.user_id == subject.id,
            subject_m.hidden.is_(False),
        )
        .order_by(League.is_global, League.name)
    )
    return list(db.session.scalars(stmt))


# -----------------------------------------------------------------------------
# Lineups
# -----------------------------------------------------------------------------


def visible_snapshot(viewer, subject, meeting, now: datetime | None = None):
    """`subject`'s effective lineup at one meeting, if `viewer` may see it.

    Effective, not committed: snapshots are sparse (§5), so a player who last
    picked at meeting 3 still has a lineup at meeting 7 and it is meeting 3's.

    The lock is tested against the meeting being *asked about*, not against the
    meeting the snapshot was committed for. Asking "what was your lineup at
    Berlin" when Berlin is locked is permitted, and which earlier row supplied
    that lineup is not a separate disclosure — it is the same five picks.
    """
    now = now or _utcnow()
    if meeting.deadline_at is None or meeting.deadline_at > now:
        return None
    if not can_view(viewer, subject):
        return None

    stmt = (
        select(LineupSnapshot)
        .join(Meeting, LineupSnapshot.meeting_id == Meeting.id)
        .where(
            LineupSnapshot.user_id == subject.id,
            Meeting.season_id == meeting.season_id,
            Meeting.sequence <= meeting.sequence,
        )
        .order_by(Meeting.sequence.desc())
        .limit(1)
    )
    return db.session.scalars(stmt).first()


def visible_season_lineups(
    viewer, subject, season: Season, now: datetime | None = None
) -> list[tuple[Meeting, LineupSnapshot | None]]:
    """Every locked meeting of a season with the lineup that was effective.

    The shape a friend profile wants: one row per weekend that has happened,
    carrying the five picks that scored it, and `None` for a weekend the player
    had no lineup for at all.

    Unlocked meetings are not in the list — not blank rows, absent rows. A
    blank row for the open weekend invites a reader to wonder whether the
    player has picked yet, which is exactly the fact §2 hides.

    Two queries: the locked calendar, and the subject's snapshots bounded by
    the last locked sequence. The carry-forward is then a walk in Python. The
    bound is what makes an unlocked snapshot unreachable rather than merely
    unreached.
    """
    now = now or _utcnow()
    if not can_view(viewer, subject):
        return []

    meetings = list(
        db.session.scalars(
            select(Meeting)
            .where(Meeting.season_id == season.id, locked_clause(now))
            .order_by(Meeting.sequence)
        )
    )
    if not meetings:
        return []

    ceiling = meetings[-1].sequence
    rows_out = db.session.execute(
        select(LineupSnapshot, Meeting.sequence)
        .join(Meeting, LineupSnapshot.meeting_id == Meeting.id)
        .where(
            LineupSnapshot.user_id == subject.id,
            Meeting.season_id == season.id,
            Meeting.sequence <= ceiling,
        )
        .order_by(Meeting.sequence)
    )

    # Selected alongside rather than read off `snapshot.meeting`, which would
    # be one lazy load per weekend on a page that already has the calendar.
    by_sequence = {sequence: snapshot for snapshot, sequence in rows_out}
    rows: list[tuple[Meeting, LineupSnapshot | None]] = []
    carried: LineupSnapshot | None = None
    for meeting in meetings:
        carried = by_sequence.get(meeting.sequence, carried)
        rows.append((meeting, carried))
    return rows


def visible_snapshots_at(viewer, meeting, now: datetime | None = None):
    """Every visible player's effective lineup at one locked meeting.

    The set-wide form, for a league's weekend view. It is
    `service.effective_snapshots` with the two predicates applied — which is
    why that function stays as it is rather than growing a `viewer` argument:
    the scoring pass must see everyone, and a scoring pass that could be
    filtered by a viewer is a scoring pass someone will one day filter.
    """
    now = now or _utcnow()
    if meeting.deadline_at is None or meeting.deadline_at > now:
        return []
    if viewer is None or not getattr(viewer, "is_authenticated", True):
        return []

    stmt = (
        select(LineupSnapshot)
        .join(Meeting, LineupSnapshot.meeting_id == Meeting.id)
        .where(
            Meeting.season_id == meeting.season_id,
            Meeting.sequence <= meeting.sequence,
            # The `or_` mirrors `can_view`'s self short-circuit. Without it a
            # member hidden in their only league drops out of their own
            # weekend view, which reads as a bug rather than as privacy.
            or_(
                LineupSnapshot.user_id == viewer.id,
                shared_league_clause(viewer.id, LineupSnapshot.user_id),
            ),
        )
        .order_by(LineupSnapshot.user_id, Meeting.sequence.desc())
        .distinct(LineupSnapshot.user_id)
    )
    return list(db.session.scalars(stmt))
