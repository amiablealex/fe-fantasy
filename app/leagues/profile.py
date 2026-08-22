"""Another player's season.

Two reads, deliberately separated by cost.

`player_profile` is the cheap one: every locked weekend, what was picked, what
it cost in transfers and what it scored. One `GROUP BY` over `PickScore` plus
the visibility layer's carry-forward walk, and it is the whole page for a
player who only wants the shape of someone's season.

`weekend_detail` is the expensive one and runs for exactly one weekend.
`scoring_bridge.score_meeting` reads the round's results as well as its stored
scores — the context line under each pick ("Started P13, finished P5") is a
different question from what scored, and no stored score answers it. Thirteen
of those on one page would be thirteen result reads to render a list.

**Everything foreign goes through `app/leagues/visibility.py`.** Nothing in
this module queries `LineupSnapshot` directly, which is what stops a future
endpoint here from being the one that forgets the deadline.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.extensions import db
from app.leagues import visibility
from app.meetings import scoring_bridge as bridge
from app.models.calendar import Meeting
from app.models.league import League
from app.models.lineup import LineupSnapshot
from app.models.score import PickScore
from app.models.user import User

ZERO = Decimal(0)


@dataclass(frozen=True)
class WeekendRow:
    meeting: Meeting
    snapshot: LineupSnapshot | None
    committed: bool
    transfer_cost: int | None
    points: Decimal | None

    @property
    def scored(self) -> bool:
        return self.points is not None


@dataclass(frozen=True)
class PlayerProfile:
    user: User
    is_you: bool
    leagues: list[League]
    weekends: list[WeekendRow]
    total: Decimal
    played: int

    @property
    def latest_with_lineup(self) -> Meeting | None:
        """The weekend a profile opens on.

        Newest first, so this is simply the first row that has a lineup behind
        it. A profile is mostly read to answer "how are they doing lately".
        """
        for row in self.weekends:
            if row.snapshot is not None:
                return row.meeting
        return None

    def row_for(self, sequence: int) -> WeekendRow | None:
        return next(
            (row for row in self.weekends if row.meeting.sequence == sequence), None
        )


def _points_by_meeting(subject: User, season) -> dict[int, Decimal]:
    stmt = (
        select(PickScore.meeting_id, func.sum(PickScore.points))
        .where(
            PickScore.user_id == subject.id,
            PickScore.season_id == season.id,
        )
        .group_by(PickScore.meeting_id)
    )
    return {meeting_id: total or ZERO for meeting_id, total in db.session.execute(stmt)}


def player_profile(
    viewer: User, subject: User, season, now: datetime | None = None
) -> PlayerProfile:
    """A player's season, newest weekend first.

    An unlocked weekend is absent rather than blank. A blank row for the open
    weekend invites the reader to wonder whether they have picked yet, which is
    exactly the fact SPEC.md §2 hides.
    """
    rows = visibility.visible_season_lineups(viewer, subject, season, now=now)
    points = _points_by_meeting(subject, season)

    weekends: list[WeekendRow] = []
    for meeting, snapshot in rows:
        committed = snapshot is not None and snapshot.meeting_id == meeting.id
        weekends.append(
            WeekendRow(
                meeting=meeting,
                snapshot=snapshot,
                committed=committed,
                # The stored slot diff, which is a past fact about a locked
                # weekend. Not the transfer *bank*, which moves the moment they
                # commit for the open weekend and would leak whether they have.
                transfer_cost=snapshot.transfer_cost if committed else None,
                points=points.get(meeting.id),
            )
        )
    weekends.reverse()

    scored = [row.points for row in weekends if row.points is not None]
    return PlayerProfile(
        user=subject,
        is_you=viewer is not None and viewer.id == subject.id,
        leagues=visibility.shared_leagues(viewer, subject),
        weekends=weekends,
        total=sum(scored, ZERO),
        played=len(scored),
    )


@dataclass(frozen=True)
class WeekendDetail:
    meeting: Meeting
    picks: list
    total: Decimal
    dream_tied: int


def weekend_detail(
    viewer: User, subject: User, season, meeting: Meeting, now: datetime | None = None
) -> WeekendDetail | None:
    """One weekend's lineup, scored, in the shape the lineup component wants.

    Returns None when the weekend is not visible or the player had no lineup —
    the two are the same thing to the page, which is why the visibility check
    is the first line rather than a decoration on the query.
    """
    snapshot = visibility.visible_snapshot(viewer, subject, meeting, now=now)
    if snapshot is None or not snapshot.is_complete:
        return None

    breakdowns = bridge.score_meeting(season, meeting, snapshot.to_lineup())
    picks = bridge.aggregate_meeting(breakdowns)
    if not picks:
        return None

    best = bridge.meeting_best_lineup(season, meeting)
    bridge.mark_best(picks, best.lineup)

    return WeekendDetail(
        meeting=meeting,
        picks=picks,
        total=sum((b.total for b in breakdowns if b.scored), ZERO),
        dream_tied=best.tied,
    )
