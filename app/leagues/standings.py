"""League standings.

One aggregate query, pivoted in Python. SPEC.md §2 settled the shape of this
long before there was anything to run it against: a lineup scores once per user
and projects into every league they belong to, so league membership is a
*filter* over `PickScore` and never a scoring context. There is no per-league
arithmetic anywhere in this file — only a `GROUP BY` and a sort.

Three consequences of that, which between them answer §10's late-joiner
question:

- **Joining a league late costs nothing.** The table is season totals for
  current members. Someone who has been playing since December and joins your
  league in March brings their whole season with them.
- **There is therefore no `joined_at` scoping**, and so no leave-and-rejoin
  exploit — a player having a bad season cannot wipe it by rejoining.
- The residue is a genuinely new *account* mid-season, which no table shape
  fixes without inventing points. The `last` window below is the answer to
  that: it is a real ranking over a range everyone shares.

**Provisional scores are included.** §3 makes a partial round score a
monotonically increasing partial sum, so a Saturday-afternoon total is honest
rather than provisional-in-the-misleading-sense. It still has to be *marked*,
or a reader takes a half-scored weekend for a finished one.

**Hidden members are excluded from the table entirely, including from their own
view.** That is deliberately unlike `visibility.visible_snapshots_at`, which
shows a hidden viewer their own row. A grid of lineups is a set; a ranking is
an ordering, and an ordering that differs depending on who is looking makes
"third" mean nothing. A hidden viewer gets a notice instead of a row.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from flask import current_app
from sqlalchemy import and_, func, select

from app.extensions import db
from app.leagues import service
from app.models.calendar import Meeting, Round
from app.models.league import League, LeagueMembership
from app.models.score import PickScore
from app.models.user import User

ZERO = Decimal(0)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class StandingRow:
    user_id: int
    username: str
    position: int
    tied: bool
    total: Decimal
    last: Decimal | None
    played: int
    movement: int | None
    is_you: bool


@dataclass(frozen=True)
class Standings:
    meetings: list[Meeting]
    rows: list[StandingRow]
    viewer_hidden: bool
    provisional: bool
    truncated: bool
    window: int | None

    @property
    def is_empty(self) -> bool:
        return not self.meetings

    @property
    def latest(self) -> Meeting | None:
        return self.meetings[-1] if self.meetings else None


# -----------------------------------------------------------------------------
# Pieces
# -----------------------------------------------------------------------------


def locked_meetings(season, now: datetime, window: int | None = None) -> list[Meeting]:
    """The weekends the table covers.

    A meeting with no deadline yet is not locked — the same reading
    `grace_meeting` and `visibility.locked_clause` take, and the reason an
    unsynced calendar cannot leak a weekend into the standings.
    """
    meetings = list(
        db.session.scalars(
            select(Meeting)
            .where(
                Meeting.season_id == season.id,
                Meeting.deadline_at.is_not(None),
                Meeting.deadline_at <= now,
            )
            .order_by(Meeting.sequence)
        )
    )
    if window and window > 0:
        meetings = meetings[-window:]
    return meetings


def visible_members(league: League) -> list[tuple[int, str]]:
    stmt = (
        select(User.id, User.username)
        .join(LeagueMembership, LeagueMembership.user_id == User.id)
        .where(
            LeagueMembership.league_id == league.id,
            LeagueMembership.hidden.is_(False),
        )
        .order_by(User.username)
    )
    return [(user_id, username) for user_id, username in db.session.execute(stmt)]


def _points_by_user_meeting(
    league: League, season, meetings: list[Meeting]
) -> dict[int, dict[int, Decimal]]:
    """The one query. Grouped by user and meeting, membership as a join.

    A join rather than `user_id IN (...)`: the global league has no member cap,
    and an IN list is the shape that stops working first.
    """
    if not meetings:
        return {}

    stmt = (
        select(
            PickScore.user_id,
            PickScore.meeting_id,
            func.sum(PickScore.points),
        )
        .join(
            LeagueMembership,
            and_(
                LeagueMembership.user_id == PickScore.user_id,
                LeagueMembership.league_id == league.id,
                LeagueMembership.hidden.is_(False),
            ),
        )
        .where(
            PickScore.season_id == season.id,
            PickScore.meeting_id.in_([m.id for m in meetings]),
        )
        .group_by(PickScore.user_id, PickScore.meeting_id)
    )

    out: dict[int, dict[int, Decimal]] = {}
    for user_id, meeting_id, total in db.session.execute(stmt):
        out.setdefault(user_id, {})[meeting_id] = total or ZERO
    return out


def _rank(totals: dict[int, Decimal], names: dict[int, str]) -> dict[int, int]:
    """Standard competition ranking: 1, 2, 2, 4.

    Ordered by total, then by username. The username is a stable display order
    within a tie, not a tiebreak — inventing a countback the game rules do not
    have would be worse than showing equal scores as equal.
    """
    ordered = sorted(
        totals.items(), key=lambda item: (-item[1], names.get(item[0], ""))
    )
    positions: dict[int, int] = {}
    previous: Decimal | None = None
    position = 0
    for index, (user_id, total) in enumerate(ordered, start=1):
        if previous is None or total != previous:
            position = index
            previous = total
        positions[user_id] = position
    return positions


def _is_provisional(meeting: Meeting | None) -> bool:
    if meeting is None:
        return False
    return bool(
        db.session.scalar(
            select(func.count())
            .select_from(Round)
            .where(
                Round.meeting_id == meeting.id,
                Round.scoring_provisional.is_(True),
            )
        )
    )


# -----------------------------------------------------------------------------
# The whole table
# -----------------------------------------------------------------------------


def standings(
    league: League,
    season,
    viewer=None,
    now: datetime | None = None,
    window: int | None = None,
) -> Standings:
    """The league table over a season, optionally over the last N weekends.

    `window` is the answer to two separate questions with one mechanism: "who
    is in form" and "how is this league doing since we all actually started".
    It is a view control rather than a stored per-league setting, because a
    start point is inherently per (league, season) and storing it needs a table
    nobody has asked for yet.
    """
    now = now or _utcnow()
    meetings = locked_meetings(season, now, window)
    members = visible_members(league)
    names = {user_id: username for user_id, username in members}

    viewer_id = viewer.id if viewer is not None else None
    viewer_hidden = viewer_id is not None and viewer_id not in names

    scores = _points_by_user_meeting(league, season, meetings)
    latest = meetings[-1] if meetings else None
    earlier = meetings[:-1]

    totals = {
        user_id: sum(scores.get(user_id, {}).values(), ZERO) for user_id, _ in members
    }
    positions = _rank(totals, names)

    # Movement is the same ranking one weekend ago. Free, because the pivot the
    # table is built from already holds every weekend separately.
    movement: dict[int, int] = {}
    if earlier:
        earlier_ids = {m.id for m in earlier}
        before = {
            user_id: sum(
                (
                    points
                    for meeting_id, points in scores.get(user_id, {}).items()
                    if meeting_id in earlier_ids
                ),
                ZERO,
            )
            for user_id, _ in members
        }
        previous_positions = _rank(before, names)
        movement = {
            user_id: previous_positions[user_id] - positions[user_id]
            for user_id, _ in members
        }

    tie_counts: dict[int, int] = {}
    for user_id in totals:
        tie_counts[positions[user_id]] = tie_counts.get(positions[user_id], 0) + 1

    rows = [
        StandingRow(
            user_id=user_id,
            username=username,
            position=positions[user_id],
            tied=tie_counts[positions[user_id]] > 1,
            total=totals[user_id],
            last=(scores.get(user_id, {}).get(latest.id) if latest else None),
            played=len(scores.get(user_id, {})),
            movement=movement.get(user_id),
            is_you=user_id == viewer_id,
        )
        for user_id, username in members
    ]
    rows.sort(key=lambda row: (row.position, row.username))

    ceiling = current_app.config["LEAGUE_TABLE_MAX_ROWS"]
    truncated = len(rows) > ceiling
    if truncated:
        shown = rows[:ceiling]
        # Keep the viewer on screen even when they are outside the cut. A table
        # that does not contain you is not your league table.
        if viewer_id is not None and all(row.user_id != viewer_id for row in shown):
            mine = next((row for row in rows if row.user_id == viewer_id), None)
            if mine is not None:
                shown = shown + [mine]
        rows = shown

    return Standings(
        meetings=meetings,
        rows=rows,
        viewer_hidden=viewer_hidden,
        provisional=_is_provisional(latest),
        truncated=truncated,
        window=window,
    )


# -----------------------------------------------------------------------------
# One player, across their leagues
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class LeagueStanding:
    """Where one player sits in one league. For the front page."""

    league: League
    position: int | None
    tied: bool
    total: Decimal
    members: int

    @property
    def is_ranked(self) -> bool:
        return self.position is not None


def standings_for_user(user, season, now: datetime | None = None) -> list[LeagueStanding]:
    """Every league the player is in, with their position in each.

    **This computes each table in full and then reads one row.** Honest about
    the cost rather than hiding it: at friend scale it is a handful of small
    aggregates, and the global league is the one that eventually is not. The
    replacement when that happens is a counting query — how many members have a
    higher total — not a cache, because a cached position is wrong for as long
    as it is stale and a league table is read on exactly the days it moves.

    `position` is None when the player is hidden in that league, which is the
    one case where they are legitimately absent from their own table.
    """
    out: list[LeagueStanding] = []
    for league, _ in service.user_leagues(user):
        table = standings(league, season, viewer=user, now=now)
        if table.is_empty:
            continue
        row = next((r for r in table.rows if r.user_id == user.id), None)
        out.append(LeagueStanding(
            league=league,
            position=row.position if row else None,
            tied=bool(row and row.tied),
            total=row.total if row else ZERO,
            members=len(visible_members(league)),
        ))
    return out
