"""Reads, returning shapes a template can consume directly.

The third of the four modules `scoring_bridge` became. Everything here is a
`select()` and a reshaping; nothing scores, nothing words anything, and nothing
takes a lineup. Callers are routes.

The dataclasses are deliberately not ORM objects. A route that hands a template
a `Round` invites the template to walk a relationship and issue a query per row;
handing it a `MeetingRef` cannot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.lineups.roster import roster_for_round, seat_entries
from app.meetings import display
from app.meetings.reads import round_scores as stored_round_scores
from app.meetings.reads import season_scores as stored_season_scores
from app.models.calendar import STAGE_RACE, Meeting, Round, Season, Session
from app.models.grid import Driver, Team
from app.models.score import SUBJECT_TEAM, RoundScore
from app.scoring.engine import fastest_lap_driver_ids

ZERO = Decimal(0)


# -----------------------------------------------------------------------------
# Meetings
# -----------------------------------------------------------------------------


def meetings(season: Season) -> list[Meeting]:
    stmt = (
        select(Meeting)
        .where(Meeting.season_id == season.id)
        .options(
            joinedload(Meeting.location),
            selectinload(Meeting.rounds),
        )
        .order_by(Meeting.sequence)
    )
    return list(db.session.scalars(stmt).unique())


def get_meeting(season: Season, sequence: int) -> Meeting | None:
    stmt = (
        select(Meeting)
        .where(Meeting.season_id == season.id, Meeting.sequence == sequence)
        .options(
            joinedload(Meeting.location),
            selectinload(Meeting.rounds)
            .selectinload(Round.sessions)
            .selectinload(Session.results),
        )
    )
    return db.session.scalars(stmt).unique().one_or_none()


# -----------------------------------------------------------------------------
# Navigation
# -----------------------------------------------------------------------------


@dataclass
class MeetingRef:
    """One entry in the meeting nav.

    `points` and `note` are optional and unset on the weekend view, where the
    nav is about the calendar. The friend profile sets them, because there the
    same list is also the season at a glance — what each weekend scored and
    what it cost in transfers. One menu carrying both beats a menu for moving
    and a list for reading, which is what that page had.
    """

    sequence: int
    name: str
    scored: bool
    provisional: bool
    rounds: list[int]
    points: Decimal | None = None
    note: str | None = None

    @property
    def is_double_header(self) -> bool:
        return len(self.rounds) > 1


def meeting_refs(season: Season) -> list[MeetingRef]:
    """Every meeting, in calendar order, and whether it has been scored.

    Cheap enough to run on every page: eleven rows in S12, thirteen in S13.

    `scored` reads `Round.scored_at`, not whether any session has results. Those
    diverged the moment partial scoring shipped: a Saturday weekend with
    qualifying ingested and no race has results and no scores, and calling it
    scored puts a figure-shaped hole in the nav. `provisional` carries the other
    half of the same fact, so a caller can say "so far" rather than implying a
    weekend is finished.
    """
    refs = []
    for meeting in meetings(season):
        rounds = sorted(meeting.rounds, key=lambda r: r.round_number)
        scored_rounds = [r for r in rounds if r.scored_at is not None]
        refs.append(MeetingRef(
            sequence=meeting.sequence,
            name=meeting.display_name,
            scored=bool(scored_rounds),
            # Provisional if anything about the weekend is still incomplete:
            # a round mid-score, or a double-header with only one round in.
            provisional=(
                any(r.scoring_provisional for r in scored_rounds)
                or 0 < len(scored_rounds) < len(rounds)
            ),
            rounds=[r.round_number for r in rounds],
        ))
    return refs


def latest_scored(refs: list[MeetingRef]) -> int | None:
    scored = [r.sequence for r in refs if r.scored]
    return max(scored) if scored else None


@dataclass
class Neighbours:
    previous: int | None
    next: int | None
    current: MeetingRef | None


def neighbours(refs: list[MeetingRef], sequence: int) -> Neighbours:
    """Previous and next meeting, or None at either end.

    None means the arrow is shown flat rather than removed. A control that
    disappears makes the layout jump and teaches nothing; a flat one says you
    are at the end.
    """
    order = [r.sequence for r in refs]
    current = next((r for r in refs if r.sequence == sequence), None)
    if sequence not in order:
        return Neighbours(None, None, current)
    index = order.index(sequence)
    return Neighbours(
        previous=order[index - 1] if index > 0 else None,
        next=order[index + 1] if index < len(order) - 1 else None,
        current=current,
    )


# -----------------------------------------------------------------------------
# Results and schedule
# -----------------------------------------------------------------------------


@dataclass
class StageResults:
    """One qualifying session's classification, in bracket order."""

    stage: str
    stage_index: int | None
    name: str
    rows: list


@dataclass
class RoundResults:
    round: Round
    qualifying: list[StageResults]
    race: list
    has_results: bool
    # Whoever set the quickest lap, by parsed time. A set, because an exact tie
    # must not be resolved by list order.
    fastest_driver_ids: frozenset = frozenset()


# Bracket order, so a round reads groups then duels regardless of how the
# provider ordered its schedule.
_STAGE_ORDER = {
    "group": 0,
    "quarter_final": 1,
    "semi_final": 2,
    "final": 3,
}


def round_results(round_obj: Round) -> RoundResults:
    qualifying: list[StageResults] = []
    race: list = []

    for session in sorted(round_obj.sessions, key=lambda s: s.ordinal):
        rows = sorted(
            session.results,
            key=lambda r: (r.position is None, r.position or 0),
        )
        if session.stage == STAGE_RACE:
            race = rows
        elif session.is_scoring_qualifying and rows:
            qualifying.append(StageResults(
                stage=session.stage,
                stage_index=session.stage_index,
                name=session.name,
                rows=rows,
            ))

    qualifying.sort(key=lambda s: (_STAGE_ORDER.get(s.stage, 9), s.stage_index or 0))

    # Derived from the minimum lap time and never from `fastest_lap_rank`: that
    # field marks the fastest lap among championship-eligible drivers, which
    # silently reimposes Formula E's top-ten restriction. This game's point is
    # unconditional, and rank disagrees on eight of seventeen Season 12 rounds
    # (SPEC.md §3). The engine owns the derivation so the star in the
    # classification cannot mark a different row from the one the score credits.
    fastest = fastest_lap_driver_ids(
        [{"driver_id": r.driver_id, "lap_time": r.lap_time} for r in race]
    )

    return RoundResults(
        round=round_obj,
        qualifying=qualifying,
        race=race,
        has_results=bool(race or qualifying),
        fastest_driver_ids=frozenset(fastest),
    )


@dataclass
class ScheduledSession:
    name: str
    type: str
    start_time: Any
    status: str | None


def round_schedule(round_obj: Round) -> list[ScheduledSession]:
    """Every session of a round in schedule order, results or not.

    What a meeting has to show before it has been raced. Practice and shakedown
    sessions are included here even though they are never ingested for results —
    the reader wants the weekend, not the scoring surface.
    """
    return [
        ScheduledSession(
            name=session.name,
            type=session.type,
            start_time=session.start_time,
            status=session.status,
        )
        for session in sorted(round_obj.sessions, key=lambda s: s.ordinal)
    ]


# -----------------------------------------------------------------------------
# Profiles
# -----------------------------------------------------------------------------


@dataclass
class ProfileRow:
    round_number: int
    format_label: str
    total: Decimal
    cells: dict           # column key -> Decimal
    took_part: bool


@dataclass
class Profile:
    subject: Any
    team: Team | None
    kind: str                     # "driver" | "team"
    rows: list[ProfileRow]
    totals: dict
    grand_total: Decimal
    # Team profiles only: the two cars, and their per-round scores.
    cars: list = None
    car_rows: list = None
    # Every other season this subject scored in. Empty until a second season
    # exists, which is the correct rendering of "no history".
    history: list = field(default_factory=list)


def round_scores(round_obj: Round):
    """One round's stored scores, in the engine's own shape.

    What the FP column in a classification reads. `RoundScore` is
    user-independent — thirty rows a round whether the league has three players
    or three hundred — so this is the same query for everyone looking at the
    page, and "what was this drive worth" is answered once rather than per
    reader.
    """
    return stored_round_scores(round_obj)


def season_scores(season: Season) -> dict:
    """Every scored round of a season. A read, from Phase 5 onward.

    This used to rescore seventeen rounds on every profile view — loading
    roughly nine hundred result rows and running the engine over all of them to
    render one column of one table. It is now one indexed query against the rows
    the scoring pass already wrote.

    The objects it returns are shaped exactly like the engine's, which is why
    the profile templates did not have to change.
    """
    return stored_season_scores(season)


def subject_history(kind: str, subject_id: Any, exclude_season: Season) -> list:
    """What this driver or team scored in every season but the one on screen.

    Fantasy points, and only fantasy points. There is no attempt to reconstruct
    a career from Formula E's own championship results: the fantasy ruleset was
    tuned against Season 12's format, the duels qualifying it scores did not
    exist before Season 8, and a figure for Season 3 would look authoritative
    and mean nothing. This game starts counting when this game started.

    The current season is excluded because the wide table above already is that
    season, in full — repeating its total two inches lower invites the reader to
    check the arithmetic against a figure that is the same figure.

    One `GROUP BY` over rows the scoring pass already wrote. No migration, no
    provider call: `RoundScore` is season-scoped and user-independent, so a
    driver's history is a sum over rows that were stored the day each round was
    scored.
    """
    subject_column = (
        RoundScore.team_id if kind == "team" else RoundScore.driver_id
    )
    kind_clause = (
        RoundScore.kind == SUBJECT_TEAM
        if kind == "team"
        else RoundScore.kind != SUBJECT_TEAM
    )

    stmt = (
        select(Season, db.func.sum(RoundScore.points))
        .join(Season, RoundScore.season_id == Season.id)
        .where(
            subject_column == subject_id,
            kind_clause,
            RoundScore.season_id != exclude_season.id,
        )
        .group_by(Season.id)
        .order_by(Season.year.desc())
    )
    return [
        {"season": season, "total": total or ZERO}
        for season, total in db.session.execute(stmt)
    ]


def _cells_for(score) -> dict:
    """One round's components, collapsed onto the profile's columns."""
    cells = {key: ZERO for key, _, _ in display.PROFILE_COLUMNS}
    for component in score.components:
        key = display.profile_column_key(component.rule)
        if key in cells:
            cells[key] += component.points
    return cells


def driver_profile(season: Season, driver_id: Any) -> Profile | None:
    """A driver's season, and their history before it.

    **Returns a profile even when the season has scored nothing.** For eleven
    weeks between the Season 13 calendar landing and Jeddah, that is every
    driver — and it is exactly the window in which "how did this one do last
    year" is the only question worth asking, which the history block answers.
    An earlier version returned None there, so the info mark in the picker
    would have opened nothing at all during the one period it is most useful.

    None still means the driver does not exist.
    """
    driver = db.session.get(Driver, driver_id)
    if driver is None:
        return None

    scored = season_scores(season)
    if not scored:
        seats = seat_entries(season)
        team = None
        for seat in seats:
            if seat.driver_id == driver_id:
                team = seat.team
                break
        return Profile(
            subject=driver, team=team, kind="driver",
            rows=[], totals={}, grand_total=ZERO,
            history=subject_history("driver", driver_id, season),
        )

    rows: list[ProfileRow] = []
    totals = {key: ZERO for key, _, _ in display.PROFILE_COLUMNS}
    grand = ZERO
    team = None
    seats = seat_entries(season)

    for round_number in sorted(scored):
        round_obj, score = scored[round_number]
        took_part = driver_id in score.drivers
        driver_score = score.score_for(driver_id)
        cells = _cells_for(driver_score)

        for key, value in cells.items():
            totals[key] += value
        grand += driver_score.total

        rows.append(ProfileRow(
            round_number=round_number,
            format_label=round_obj.format_label,
            total=driver_score.total,
            cells=cells,
            took_part=took_part,
        ))

        if team is None:
            roster = roster_for_round(season, round_number, seats=seats)
            team = roster.team_for(driver_id)

    return Profile(
        subject=driver, team=team, kind="driver",
        rows=rows, totals=totals, grand_total=grand,
        history=subject_history("driver", driver_id, season),
    )


def team_profile(season: Season, team_id: Any) -> Profile | None:
    """A team's season: both cars per round, and what the pick scored.

    Showing the halves beside the sum makes the half-sum rule explain itself,
    which is the same trick the breakdown's "Half of Cassidy 9, Vergne 0" line
    does.

    Like `driver_profile`, this answers before the season has scored anything —
    with an empty table and whatever history there is.
    """
    team = db.session.get(Team, team_id)
    if team is None:
        return None

    scored = season_scores(season)
    if not scored:
        return Profile(
            subject=team, team=team, kind="team",
            rows=[], totals={}, grand_total=ZERO,
            cars=[], car_rows=[],
            history=subject_history("team", team_id, season),
        )

    car_ids: list = []
    rows: list[ProfileRow] = []
    car_rows: list = []
    grand = ZERO
    seats = seat_entries(season)

    for round_number in sorted(scored):
        round_obj, score = scored[round_number]
        roster = roster_for_round(season, round_number, seats=seats)
        cars = roster.drivers_by_team.get(team_id, [])
        for car in cars:
            if car not in car_ids:
                car_ids.append(car)

        # The stored half-sum, not a recomputation. Recomputing would use
        # whichever divisor is current rather than the one this round recorded.
        team_total = score.team_total(team_id)
        grand += team_total

        car_rows.append({
            "round_number": round_number,
            "format_label": round_obj.format_label,
            "cars": {car: score.total_for(car) for car in cars},
            "total": team_total,
        })
        rows.append(ProfileRow(
            round_number=round_number,
            format_label=round_obj.format_label,
            total=team_total,
            cells={},
            took_part=bool(cars),
        ))

    roster = roster_for_round(season, min(scored), seats=seats)
    cars = [roster.drivers.get(c) for c in car_ids]

    car_totals = {
        car_id: sum((r["cars"].get(car_id, ZERO) for r in car_rows), ZERO)
        for car_id in car_ids
    }

    return Profile(
        subject=team, team=team, kind="team",
        rows=rows, totals=car_totals, grand_total=grand,
        cars=[c for c in cars if c], car_rows=car_rows,
        history=subject_history("team", team_id, season),
    )
