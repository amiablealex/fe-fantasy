"""The game rules, applied to stored snapshots.

`app/scoring/lineups.py` holds the rules themselves and knows nothing about a
database, a user or a calendar. This module is what connects them: it answers
which weekend is open, what a player is allowed to change, what it costs, and
it writes the result.

Everything here is a plain function over the ORM. Nothing imports Flask beyond
the session, so the whole surface is testable without HTTP — which matters,
because the route in the next stage is a thin wrapper and the rules are not.

Four things are derived rather than stored, per SPEC.md §5:

    the effective lineup   the latest snapshot at or before a meeting
    the transfer bank      a walk over the costs of the charged meetings
    the grace period       a function of the user's join date and the calendar
    the open weekend       the earliest meeting whose deadline has not passed

Storing any of them would create a second source of truth that drifts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from app.extensions import db
from app.lineups.roster import Roster, roster_for_round
from app.models.calendar import Meeting, Season
from app.models.lineup import LineupSnapshot
from app.models.user import User
from app.scoring import lineups as rules


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CommitRefused(Exception):
    """A lineup the server will not store, and why.

    `problems` carries the individual broken rules where there are several, so
    the editor can list them in the same place it lists a draft's problems. The
    message is what to say when there is only one thing to say.
    """

    def __init__(self, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.problems = problems or [message]


# -----------------------------------------------------------------------------
# The calendar
# -----------------------------------------------------------------------------


def season_meetings(season: Season) -> list[Meeting]:
    stmt = (
        select(Meeting)
        .where(Meeting.season_id == season.id)
        .order_by(Meeting.sequence)
    )
    return list(db.session.scalars(stmt))


def open_meeting(season: Season, now: datetime | None = None) -> Meeting | None:
    """The one weekend a lineup may be edited for.

    Only the earliest unlocked meeting is editable. Letting a player set their
    meeting 9 lineup while meeting 8 is still open would make meeting 9's
    transfer cost depend on a baseline that is still moving, and there is no
    honest number to show them while that is true.

    None means every meeting is locked: the season is over.
    """
    now = now or _utcnow()
    for meeting in season_meetings(season):
        if not meeting.is_locked(now):
            return meeting
    return None


def latest_locked_meeting(season: Season, now: datetime | None = None) -> Meeting | None:
    """The most recent weekend whose deadline has passed.

    The weekend that is *live*, as opposed to the one that is editable. During
    a race weekend those are different meetings, and the front page is about
    this one: your picks are in, they are being scored, and next weekend's
    editor is a link rather than the headline.

    None means the season has not started.
    """
    now = now or _utcnow()
    locked = [m for m in season_meetings(season) if m.is_locked(now)]
    return locked[-1] if locked else None


def first_round_number(meeting: Meeting) -> int:
    """The roster resolves against a meeting's first round.

    A mid-season team switch means "which team is this driver on" has no answer
    at meeting level, and the lineup locks before the first round runs, so the
    first round is the one the constraint was checked against.
    """
    return min(r.round_number for r in meeting.rounds)


def meeting_roster(meeting: Meeting) -> Roster:
    return roster_for_round(meeting.season, first_round_number(meeting))


# -----------------------------------------------------------------------------
# Grace
# -----------------------------------------------------------------------------


def grace_meeting(user: User, season: Season) -> Meeting | None:
    """The last weekend a player may edit freely.

    SPEC.md §2: unlimited free edits until the first deadline of the season,
    with transfer accounting beginning at meeting 2. A player who joins later
    gets the same grace up to their own first deadline.

    Both cases are the same rule: find the first meeting whose deadline had not
    already passed when the account was created. That weekend is free, and
    charging begins with the one after it. For someone who registered before
    the season, that is meeting 1 — exactly what §2 describes.

    A null deadline counts as "not yet passed": an unsynced meeting is in the
    future, not in the past.

    None means every deadline in the season had already passed when the account
    was created, so there is nothing left to charge for.
    """
    created = user.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    for meeting in season_meetings(season):
        if meeting.deadline_at is None or created is None:
            return meeting
        if meeting.deadline_at > created:
            return meeting
    return None


def is_in_grace(user: User, meeting: Meeting) -> bool:
    grace = grace_meeting(user, meeting.season)
    return grace is not None and meeting.sequence <= grace.sequence


# -----------------------------------------------------------------------------
# Snapshots
# -----------------------------------------------------------------------------


def snapshot_for(user: User, meeting: Meeting) -> LineupSnapshot | None:
    """The snapshot committed for this exact meeting, if there is one."""
    stmt = select(LineupSnapshot).where(
        LineupSnapshot.user_id == user.id,
        LineupSnapshot.meeting_id == meeting.id,
    )
    return db.session.scalars(stmt).one_or_none()


def _snapshot_before(
    user: User, meeting: Meeting, *, inclusive: bool
) -> LineupSnapshot | None:
    if inclusive:
        window = Meeting.sequence <= meeting.sequence
    else:
        window = Meeting.sequence < meeting.sequence
    stmt = (
        select(LineupSnapshot)
        .join(Meeting, LineupSnapshot.meeting_id == Meeting.id)
        .where(
            LineupSnapshot.user_id == user.id,
            Meeting.season_id == meeting.season_id,
            window,
        )
        .order_by(Meeting.sequence.desc())
        .limit(1)
    )
    return db.session.scalars(stmt).first()


def previous_snapshot(user: User, meeting: Meeting) -> LineupSnapshot | None:
    """The baseline a change at this meeting is measured against.

    Strictly earlier, never this meeting's own snapshot. Re-editing a lineup
    before the deadline has to be free however many times it happens; charging
    against the last thing saved would make a player pay for changing their
    mind, and the transfer bank would depend on how often they opened the app.
    """
    return _snapshot_before(user, meeting, inclusive=False)


def effective_snapshot(user: User, meeting: Meeting) -> LineupSnapshot | None:
    """What this player's lineup actually is at this meeting.

    Snapshots are sparse: a row exists only where something was committed, so a
    player who has not touched the app since meeting 3 still has a lineup at
    meeting 7, and it is meeting 3's. This is the query that makes that true,
    and the reason no job writes carried-forward rows at every deadline.
    """
    return _snapshot_before(user, meeting, inclusive=True)


def effective_snapshots(meeting: Meeting) -> list[LineupSnapshot]:
    """Every player's effective lineup at one meeting, in one query.

    The set-wide form of `effective_snapshot`. The scoring pass needs it
    because it scores everyone at once, and Phase 6's league table needs it for
    the same reason — calling the singular version per user would issue one
    query per player per meeting.

    `DISTINCT ON (user_id)` with the matching `ORDER BY` is Postgres doing the
    at-or-before pick in the database rather than in Python. It is not portable
    SQL, which is fine: the test suite runs against real Postgres precisely so
    that a query like this is exercised rather than avoided.

    A player with no snapshot at or before this meeting is simply absent from
    the result, which is correct — they have no lineup yet and nothing to
    score.
    """
    stmt = (
        select(LineupSnapshot)
        .join(Meeting, LineupSnapshot.meeting_id == Meeting.id)
        .where(
            Meeting.season_id == meeting.season_id,
            Meeting.sequence <= meeting.sequence,
        )
        .order_by(LineupSnapshot.user_id, Meeting.sequence.desc())
        .distinct(LineupSnapshot.user_id)
    )
    return list(db.session.scalars(stmt))


def season_snapshots(user: User, season: Season) -> list[LineupSnapshot]:
    stmt = (
        select(LineupSnapshot)
        .join(Meeting, LineupSnapshot.meeting_id == Meeting.id)
        .where(
            LineupSnapshot.user_id == user.id,
            LineupSnapshot.season_id == season.id,
        )
        .order_by(Meeting.sequence)
    )
    return list(db.session.scalars(stmt))


# -----------------------------------------------------------------------------
# The transfer bank
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class TransferBudget:
    """What a player may spend at one meeting.

    `unlimited` is the grace period rather than a large number, because the two
    are different things to say. "You have 2 transfers" and "you can change
    anything until the first deadline" are not the same sentence, and a
    sentinel integer would make the editor phrase them identically.
    """

    available: int
    unlimited: bool = False

    def allows(self, cost: int) -> bool:
        return self.unlimited or cost <= self.available


def transfer_budget(user: User, meeting: Meeting) -> TransferBudget:
    """Transfers in hand for this meeting, derived from the stored costs.

    One per meeting, banking to a maximum of two, starting at one for the first
    charged weekend — a late joiner has already had unlimited edits, so
    arriving with a full bank on top would be paying them twice.

    Meetings with no snapshot cost nothing, which is what makes a player who
    forgets the app for a month come back with a full bank rather than a
    penalty.
    """
    season = meeting.season
    grace = grace_meeting(user, season)
    if grace is None or meeting.sequence <= grace.sequence:
        return TransferBudget(available=0, unlimited=True)

    costs = {s.meeting_id: s.transfer_cost for s in season_snapshots(user, season)}
    spent = [
        costs.get(earlier.id, 0)
        for earlier in season_meetings(season)
        if grace.sequence < earlier.sequence < meeting.sequence
    ]
    return TransferBudget(available=rules.transfers_available(spent))


# -----------------------------------------------------------------------------
# The whole picture, for a route
# -----------------------------------------------------------------------------


@dataclass
class LineupState:
    """Everything the editor needs about one player at one meeting."""

    meeting: Meeting
    snapshot: LineupSnapshot | None      # committed for this meeting
    previous: LineupSnapshot | None      # the cost baseline, strictly earlier
    budget: TransferBudget
    locked: bool
    editable: bool
    roster: Roster

    @property
    def baseline(self) -> rules.Lineup | None:
        """What a change is costed against. None means the first ever lineup."""
        return self.previous.to_lineup() if self.previous else None

    @property
    def starting_draft(self) -> rules.Lineup | None:
        """What the editor opens showing.

        This meeting's own snapshot if there is one, otherwise the lineup
        carried forward. Deliberately not the same as `baseline`.
        """
        source = self.snapshot or self.previous
        return source.to_lineup() if source else None

    @property
    def is_first_lineup(self) -> bool:
        return self.previous is None and self.snapshot is None


def lineup_state(
    user: User, meeting: Meeting, now: datetime | None = None
) -> LineupState:
    now = now or _utcnow()
    open_now = open_meeting(meeting.season, now)
    return LineupState(
        meeting=meeting,
        snapshot=snapshot_for(user, meeting),
        previous=previous_snapshot(user, meeting),
        budget=transfer_budget(user, meeting),
        locked=meeting.is_locked(now),
        editable=open_now is not None and open_now.id == meeting.id,
        roster=meeting_roster(meeting),
    )


# -----------------------------------------------------------------------------
# Commit
# -----------------------------------------------------------------------------


def commit(
    user: User,
    meeting: Meeting,
    lineup: rules.Lineup,
    now: datetime | None = None,
) -> LineupSnapshot:
    """Store a lineup, revalidating every rule the editor claimed to enforce.

    The draft in the URL is convenience, never authority (SPEC.md §2). Both
    sides call `app/scoring/lineups.py`, so they cannot disagree about what is
    valid — but the client can still submit a URL by hand, and the deadline can
    pass between rendering a page and posting from it.

    Checks run in the order a player would understand them: can you edit this
    weekend at all, is the lineup legal, and only then can you afford it.
    """
    now = now or _utcnow()

    if meeting.is_locked(now):
        raise CommitRefused("This weekend is locked. The deadline has passed.")

    open_now = open_meeting(meeting.season, now)
    if open_now is None or open_now.id != meeting.id:
        raise CommitRefused(
            "You can only set your lineup for the next weekend."
        )

    roster = meeting_roster(meeting)
    problems = rules.validate_lineup(lineup, roster.team_of_driver)
    if problems:
        raise CommitRefused(
            "This lineup breaks a rule.", [p.message for p in problems]
        )

    previous = previous_snapshot(user, meeting)
    cost = rules.transfer_cost(previous.to_lineup() if previous else None, lineup)

    budget = transfer_budget(user, meeting)
    if not budget.allows(cost):
        raise CommitRefused(
            f"This costs {cost} transfer{'' if cost == 1 else 's'} and you have "
            f"{budget.available}. Put one of your original picks back."
        )

    record = snapshot_for(user, meeting)
    if record is None:
        record = LineupSnapshot.build(
            user_id=user.id,
            season_id=meeting.season_id,
            meeting_id=meeting.id,
            lineup=lineup,
            transfer_cost=cost,
        )
        db.session.add(record)
    else:
        # The snapshot row survives an edit; only the picks and the cost move.
        # Keeping the row means `committed_at` stays the first commit and
        # `updated_at` tracks the last, which is the history worth having.
        record.replace_picks(lineup)
        record.transfer_cost = cost

    db.session.commit()
    return record
