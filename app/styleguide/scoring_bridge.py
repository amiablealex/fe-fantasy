"""Adapter between the database and the scoring engine.

`app/scoring/` takes plain dicts and imports nothing from Flask or SQLAlchemy,
which is what lets `sim/` run without a web application. Something has to sit
between the ORM and that contract, and this is it.

It lives under `app/styleguide/` for now because the proof screens are its only
caller. **Phase 5 promotes it to `app/meetings/`**, unchanged in shape: the
scoring worker needs exactly this translation, and writing it twice would be
how the two quietly disagree.

Nothing here scores anything. It reads rows, reshapes them, and hands them to
`app.scoring`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
# Moved to app/lineups/ in Phase 4: production code must not import from a
# debug-only package. Re-exported so this module's callers are unchanged.
from app.lineups.roster import Roster, roster_for_round
from app.models.calendar import STAGE_RACE, Meeting, Round, Season, Session
from app.models.grid import Driver, Team
from app.scoring import engine, lineups


# -----------------------------------------------------------------------------
# Reading
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


def _result_row(result) -> dict:
    """One classification row in the engine's input shape.

    Only the five keys the engine reads. Anything else would be an invitation
    for the engine to start reading it.
    """
    return {
        "driver_id": result.driver_id,
        "position": result.position,
        "grid_position": result.grid_position,
        "status": result.status,
        "lap_time": result.lap_time,
    }


def round_payload(round_obj: Round) -> tuple[list[dict], list[dict]]:
    """(qualifying sessions, race rows) for one round, engine-shaped.

    Sessions come back in schedule order, which matters: the engine derives
    pole from the Qual Final's winner, and the final has to have landed.
    """
    qualifying: list[dict] = []
    race_rows: list[dict] = []

    for session in sorted(round_obj.sessions, key=lambda s: s.ordinal):
        rows = [_result_row(r) for r in session.results]
        if session.stage == STAGE_RACE:
            race_rows = rows
        elif session.is_scoring_qualifying:
            qualifying.append({
                "stage": session.stage,
                "stage_index": session.stage_index,
                "rows": rows,
            })

    return qualifying, race_rows


def demo_lineup(roster: Roster) -> lineups.Lineup | None:
    """A stand-in lineup until Phase 4 stores real ones.

    Deliberately spread across the field rather than picked for quality: four
    drivers from four different teams at intervals through the roster, so the
    breakdown shows a strong round, a weak one, and something negative rather
    than five variations on a podium.
    """
    teams_in_order = sorted(
        roster.drivers_by_team,
        key=lambda t: (roster.teams[t].name or "") if t in roster.teams else "",
    )
    if len(teams_in_order) <= lineups.DRIVER_SLOTS:
        return None

    step = max(1, len(teams_in_order) // (lineups.DRIVER_SLOTS + 1))
    chosen_teams = [teams_in_order[i * step] for i in range(lineups.DRIVER_SLOTS)]
    picked = [sorted(roster.drivers_by_team[t])[0] for t in chosen_teams]

    spare = next(t for t in teams_in_order if t not in chosen_teams)
    return lineups.Lineup.of(picked, spare)


# -----------------------------------------------------------------------------
# Scoring a meeting
# -----------------------------------------------------------------------------


@dataclass
class PickScore:
    """One of the five slots, scored for one round, with its breakdown."""

    kind: str                      # "driver" | "team"
    label: str
    subject: Any                   # Driver or Team
    team: Team | None
    total: Decimal
    components: tuple
    in_dream_team: bool = False
    detail: str | None = None      # team picks: which two cars, and their scores
    quali_context: str | None = None
    race_context: str | None = None


@dataclass
class RoundBreakdown:
    round: Round
    picks: list[PickScore]
    total: Decimal
    dream_total: Decimal
    dream_tied: int
    issues: list[str]
    scored: bool = True


def score_meeting(
    season: Season, meeting: Meeting, lineup: lineups.Lineup
) -> list[RoundBreakdown]:
    """Score one lineup across every round of a meeting.

    A double-header scores the same lineup twice, which is the whole reason the
    meeting is the transfer unit and the round is the scoring unit.
    """
    breakdowns: list[RoundBreakdown] = []

    for round_obj in sorted(meeting.rounds, key=lambda r: r.round_number):
        qualifying, race_rows = round_payload(round_obj)
        if not race_rows:
            breakdowns.append(RoundBreakdown(
                round=round_obj, picks=[], total=Decimal(0),
                dream_total=Decimal(0), dream_tied=0,
                issues=["no race classification stored"], scored=False,
            ))
            continue

        roster = roster_for_round(season, round_obj.round_number)
        scores = engine.score_round(
            qualifying, race_rows, ruleset=None
        )

        def driver_total(driver_id: Any) -> Decimal:
            return scores.total_for(driver_id)

        def team_total(team_id: Any) -> Decimal:
            return engine.score_team(scores, roster.drivers_by_team.get(team_id, ()))

        dream = lineups.dream_team(roster.drivers_by_team, driver_total, team_total)
        dream_drivers = set()
        dream_teams = set()
        for candidate in dream.lineups:
            dream_drivers |= candidate.drivers
            dream_teams.add(candidate.team_id)

        picks: list[PickScore] = []
        for driver_id in sorted(
            lineup.drivers,
            key=lambda d: -scores.total_for(d),
        ):
            driver = roster.drivers.get(driver_id)
            score = scores.score_for(driver_id)
            picks.append(PickScore(
                kind="driver",
                label=driver.short_label if driver else str(driver_id),
                subject=driver,
                team=roster.team_for(driver_id),
                total=score.total,
                components=score.components,
                in_dream_team=driver_id in dream_drivers,
                quali_context=qualifying_context(qualifying, driver_id),
                race_context=race_context(race_rows, driver_id),
            ))

        team = roster.teams.get(lineup.team_id)
        cars = roster.drivers_by_team.get(lineup.team_id, [])
        car_detail = ", ".join(
            f"{roster.drivers[c].short_label} {scores.total_for(c)}"
            for c in sorted(cars, key=lambda c: -scores.total_for(c))
            if c in roster.drivers
        )
        picks.append(PickScore(
            kind="team",
            label=(team.name if team else str(lineup.team_id)),
            subject=team,
            team=team,
            total=team_total(lineup.team_id),
            components=(),
            in_dream_team=lineup.team_id in dream_teams,
            detail=car_detail,
        ))

        breakdowns.append(RoundBreakdown(
            round=round_obj,
            picks=picks,
            total=sum((p.total for p in picks), Decimal(0)),
            dream_total=dream.total,
            dream_tied=len(dream.lineups),
            issues=scores.issues,
        ))

    return breakdowns


# -----------------------------------------------------------------------------
# Display
# -----------------------------------------------------------------------------

# Rule identifiers are stable keys; these are what a person reads. Kept beside
# the adapter rather than in the engine, because the engine has no business
# knowing how a rule is worded in an interface.
RULE_LABELS: dict[str, str] = {
    engine.RULE_GROUP_PROGRESS: "Reached the Duels",
    engine.RULE_DUEL_WIN: "Duel win",
    engine.RULE_POLE: "Pole position",
    engine.RULE_WIN: "Race win",
    engine.RULE_PODIUM: "Podium",
    engine.RULE_POINTS_FINISH: "Points finish",
    engine.RULE_FASTEST_LAP: "Fastest lap",
    engine.RULE_PLACES_GAINED: "Places gained",
    engine.RULE_PLACES_LOST: "Places lost",
}


def rule_label(rule: str) -> str:
    return RULE_LABELS.get(rule, rule.replace("_", " ").capitalize())


# -----------------------------------------------------------------------------
# Display helpers
# -----------------------------------------------------------------------------

# What the dream team is called in the interface. Real racing vernacular rather
# than a generic superlative, and one constant so renaming it is one edit.
DREAM_TEAM_NAME = "Perfect Five"

_PLACES_DETAIL = re.compile(r"P(\d+)\s+to\s+P(\d+)")


def fmt(value) -> str:
    """A score, as a reader expects to see it.

    Halves are real and must survive — the team pick genuinely scores 5.5, and
    SPEC.md §3 forbids rounding because it introduces a bias that then needs
    explaining. But a Decimal's trailing zero is an artefact of arithmetic, not
    a fact about the score, and "25" one weekend against "26.0" the next reads
    as two different kinds of number.

    So: strip a trailing .0, keep a genuine .5.
    """
    if value is None:
        return "—"
    text = f"{Decimal(value):f}"
    # Only strip inside a fraction: rstrip on "20" would give "2".
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def component_detail(component) -> str | None:
    """The detail line for one scoring component.

    Places gained and lost are rewritten: the engine emits "P13 to P5", but the
    stage's context line already says "Started P13 · finished P5", so repeating
    it wastes the row. What the reader wants there is the figure the rule
    actually counted — eight places — because that is what produced the points.

    Rewritten here rather than in the engine because it is wording, and the
    engine has no business knowing how a rule is phrased in an interface.
    """
    detail = getattr(component, "detail", None)
    if not detail:
        return None
    if component.rule in (engine.RULE_PLACES_GAINED, engine.RULE_PLACES_LOST):
        match = _PLACES_DETAIL.search(str(detail))
        if match:
            gained = abs(int(match.group(1)) - int(match.group(2)))
            return f"{gained} places"
    return detail


# -----------------------------------------------------------------------------
# Context
# -----------------------------------------------------------------------------
#
# A breakdown that says only "no rules fired" is a non-answer: it cannot
# distinguish a driver who qualified fifteenth from one who was not on the grid
# at all. Both sections of a breakdown therefore always carry a plain sentence
# about what happened, with the scoring rows beneath it, so a zero is legible as
# a result rather than as an absence.
#
# This is derived from the raw payload rather than from the engine. Making the
# engine emit zero-point components would corrupt what "which rules fired"
# means and break `DriverRoundScore.fired()`, so the wording is the adapter's
# job — the same division as the problem messages.

_GROUP_LETTERS = {1: "A", 2: "B", 3: "C", 4: "D"}

_DUEL_LABELS = {
    engine.STAGE_QUARTER_FINAL: "Quarter-Final",
    engine.STAGE_SEMI_FINAL: "Semi-Final",
    engine.STAGE_FINAL: "Final",
}


def _row_for(rows, driver_id):
    for row in rows:
        if row.get("driver_id") == driver_id:
            return row
    return None


def qualifying_context(qualifying_sessions, driver_id) -> str | None:
    """How far a driver got in the bracket, in one sentence.

    None means they do not appear in qualifying at all, which is a different
    thing from scoring zero and must read differently.
    """
    seen = False
    group_note = None

    for session in qualifying_sessions:
        if session.get("stage") != engine.STAGE_GROUP:
            continue
        row = _row_for(session.get("rows") or [], driver_id)
        if row is None:
            continue
        seen = True
        letter = _GROUP_LETTERS.get(session.get("stage_index"), "")
        position = row.get("position")
        group_note = f"Group {letter}".strip() + (f" P{position}" if position else "")

    # Walk the bracket outwards; the last stage they appear in is where they
    # stopped, and whether they won it says whether they stopped by losing.
    furthest = None
    for stage in (engine.STAGE_QUARTER_FINAL, engine.STAGE_SEMI_FINAL,
                  engine.STAGE_FINAL):
        for session in qualifying_sessions:
            if session.get("stage") != stage:
                continue
            row = _row_for(session.get("rows") or [], driver_id)
            if row is None:
                continue
            seen = True
            furthest = (stage, row.get("position"))

    if not seen:
        return None

    if furthest is None:
        return f"Eliminated in {group_note}" if group_note else "Eliminated in the groups"

    stage, position = furthest
    label = _DUEL_LABELS.get(stage, stage)
    if stage == engine.STAGE_FINAL and position == 1:
        return "Won the Final — pole position"
    if position == 1:
        return f"Won the {label}"
    return f"Lost the {label}"


def race_context(race_rows, driver_id) -> str | None:
    """Started where, finished where. None if the driver did not start."""
    row = _row_for(race_rows, driver_id)
    if row is None:
        return None

    grid = row.get("grid_position")
    position = row.get("position")
    start = f"Started P{grid}" if grid else None

    if row.get("status"):
        end = f"retired, classified P{position}" if position else "retired"
    elif position:
        end = f"finished P{position}"
    else:
        end = "not classified"

    return f"{start} \u00b7 {end}" if start else end.capitalize()


# -----------------------------------------------------------------------------
# Meeting aggregation
# -----------------------------------------------------------------------------


@dataclass
class RoundDetail:
    """One round's contribution to one pick, split the way a reader wants it.

    Qualifying and race are kept apart rather than concatenated because they
    are separate contests with separate ceilings — 8 against 17 — and merging
    them hides which half of the weekend went well.
    """

    round: Round
    qualifying: tuple
    race: tuple
    total: Decimal
    quali_context: str | None = None
    race_context: str | None = None
    # Team picks only: which two cars, and what each scored *this round*.
    team_detail: str | None = None

    @property
    def took_part(self) -> bool:
        return bool(self.quali_context or self.race_context)


@dataclass
class PickMeetingScore:
    """One of the five slots, aggregated across a meeting.

    The lineup view shows `total` and nothing else. `rounds` is what the
    breakdown discloses on tap: a double-header's 21 is 12 and 9, and the
    reader asks for that rather than being shown it.
    """

    kind: str
    label: str
    subject: Any
    team: Team | None
    total: Decimal
    rounds: list[RoundDetail]
    in_dream_team: bool = False
    detail: str | None = None
    number: int | None = None

    @property
    def is_team(self) -> bool:
        return self.kind == "team"


def aggregate_meeting(breakdowns: list[RoundBreakdown]) -> list[PickMeetingScore]:
    """Collapse per-round breakdowns into one entry per slot.

    Slot order is preserved from the first scored round rather than re-sorted
    by score: the lineup is a fixed arrangement the player learns, and a layout
    that reshuffles by performance would make it unreadable at a glance.
    """
    scored = [b for b in breakdowns if b.scored]
    if not scored:
        return []

    order = [(p.kind, p.label) for p in scored[0].picks]
    aggregated: dict[tuple, PickMeetingScore] = {}

    for breakdown in scored:
        for pick in breakdown.picks:
            key = (pick.kind, pick.label)
            entry = aggregated.get(key)
            if entry is None:
                entry = PickMeetingScore(
                    kind=pick.kind,
                    label=pick.label,
                    subject=pick.subject,
                    team=pick.team,
                    total=Decimal(0),
                    rounds=[],
                    detail=pick.detail,
                    number=getattr(pick.subject, "number", None),
                )
                aggregated[key] = entry

            qualifying = tuple(
                c for c in pick.components
                if c.rule in (engine.RULE_GROUP_PROGRESS, engine.RULE_DUEL_WIN,
                              engine.RULE_POLE)
            )
            race = tuple(c for c in pick.components if c not in qualifying)

            entry.total += pick.total
            entry.in_dream_team = entry.in_dream_team or pick.in_dream_team
            entry.rounds.append(RoundDetail(
                round=breakdown.round,
                qualifying=qualifying,
                race=race,
                total=pick.total,
                quali_context=pick.quali_context,
                race_context=pick.race_context,
                team_detail=pick.detail,
            ))

    return [aggregated[key] for key in order if key in aggregated]


# -----------------------------------------------------------------------------
# Maximum Attack — the best possible lineup for a meeting
# -----------------------------------------------------------------------------


@dataclass
class BestLineup:
    lineup: lineups.Lineup | None
    total: Decimal
    tied: int


def meeting_best_lineup(season: Season, meeting: Meeting) -> BestLineup:
    """The highest-scoring valid lineup across a whole meeting.

    Not the same as the best lineup for each round taken separately: a
    double-header scores one lineup twice, so the question is which five picks
    maximise the *sum*. Driver and team scores are totalled across the rounds
    first, then the brute force runs once over those totals.

    Ties are kept rather than broken, per SPEC.md §3 — a high tie rate says the
    scoring gradient is too coarse, and discarding ties would discard the
    measurement.
    """
    driver_totals: dict[Any, Decimal] = {}
    team_totals: dict[Any, Decimal] = {}
    roster: Roster | None = None

    for round_obj in sorted(meeting.rounds, key=lambda r: r.round_number):
        qualifying, race_rows = round_payload(round_obj)
        if not race_rows:
            continue
        scores = engine.score_round(qualifying, race_rows)
        roster = roster_for_round(season, round_obj.round_number)

        for driver_id in roster.team_of_driver:
            driver_totals[driver_id] = (
                driver_totals.get(driver_id, Decimal(0)) + scores.total_for(driver_id)
            )
        for team_id, cars in roster.drivers_by_team.items():
            team_totals[team_id] = (
                team_totals.get(team_id, Decimal(0)) + engine.score_team(scores, cars)
            )

    if roster is None:
        return BestLineup(None, Decimal(0), 0)

    best = lineups.dream_team(
        roster.drivers_by_team,
        lambda d: driver_totals.get(d, Decimal(0)),
        lambda t: team_totals.get(t, Decimal(0)),
    )
    return BestLineup(best.best, best.total, len(best.lineups))


def mark_best(picks: list[PickMeetingScore], best: lineups.Lineup | None) -> None:
    """Star the picks that appear in the meeting's best lineup.

    Per-round stars would contradict a meeting-level total: a driver can make
    round 7's best lineup and not round 8's, and a single star against a
    combined figure has to mean one thing.
    """
    if best is None:
        for pick in picks:
            pick.in_dream_team = False
        return

    members = set(best.drivers) | {best.team_id}
    for pick in picks:
        subject_id = getattr(pick.subject, "id", None)
        pick.in_dream_team = subject_id in members


# -----------------------------------------------------------------------------
# Navigation
# -----------------------------------------------------------------------------


@dataclass
class MeetingRef:
    """One entry in the meeting nav."""

    sequence: int
    name: str
    scored: bool
    rounds: list[int]

    @property
    def is_double_header(self) -> bool:
        return len(self.rounds) > 1


def meeting_refs(season: Season) -> list[MeetingRef]:
    """Every meeting, in calendar order, and whether it has results.

    Cheap enough to run on every page: eleven rows in S12, thirteen in S13.
    """
    refs = []
    for meeting in meetings(season):
        rounds = sorted(r.round_number for r in meeting.rounds)
        scored = any(
            s.results_ingested_at is not None
            for r in meeting.rounds
            for s in r.sessions
        )
        refs.append(MeetingRef(
            sequence=meeting.sequence,
            name=meeting.display_name,
            scored=scored,
            rounds=rounds,
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
    return RoundResults(
        round=round_obj,
        qualifying=qualifying,
        race=race,
        has_results=bool(race or qualifying),
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
    sessions are included here even though they are never ingested for results
    — the reader wants the weekend, not the scoring surface.
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
#
# One wide table: every scoring route as a column, every round as a row, totals
# in bold at the foot. Not split by contest, because the question the page
# exists to answer is "how has this driver scored across the season" and a
# split gives two grand totals instead of one.
#
# Eleven columns fit a 360px viewport at --step-1 in condensed tabular figures
# — measured, not assumed. What makes it readable is not the width but
# suppressing zeros: nine columns of "0" is noise, and a blank makes the cells
# that fired legible at a glance.

# Column order groups qualifying then race, so the conceptual split survives
# without the table being cut in two.
PROFILE_COLUMNS = [
    (engine.RULE_GROUP_PROGRESS, "GRP", "Reached the Duels"),
    (engine.RULE_DUEL_WIN, "DW", "Duel wins"),
    (engine.RULE_POLE, "POL", "Pole position"),
    (engine.RULE_WIN, "WIN", "Race win"),
    (engine.RULE_PODIUM, "POD", "Podium"),
    (engine.RULE_POINTS_FINISH, "PTS", "Points finish"),
    (engine.RULE_FASTEST_LAP, "FL", "Fastest lap"),
    ("places", "±PL", "Places gained or lost"),
]

# Where the qualifying columns end, for the divider rule.
PROFILE_QUALIFYING_COLUMNS = 3

# Places gained and lost are one mechanic with a sign, so they share a column.
# Two columns, one of which is always empty, wastes width for no information.
_PLACES_RULES = (engine.RULE_PLACES_GAINED, engine.RULE_PLACES_LOST)


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


def season_scores(season: Season) -> dict:
    """Every round of a season, scored once.

    Phase 5 stores `PickScore` per round and this becomes a read. Until then
    the profile computes it, which is acceptable at seventeen rounds on a
    development machine and would not be in production.
    """
    stmt = (
        select(Round)
        .where(Round.season_id == season.id)
        .options(selectinload(Round.sessions).selectinload(Session.results))
        .order_by(Round.round_number)
    )
    out = {}
    for round_obj in db.session.scalars(stmt).unique():
        qualifying, race_rows = round_payload(round_obj)
        if not race_rows and not qualifying:
            continue
        out[round_obj.round_number] = (
            round_obj,
            engine.score_round(qualifying, race_rows),
        )
    return out


def _cells_for(score) -> dict:
    """One round's components, collapsed onto the profile's columns."""
    cells = {key: Decimal(0) for key, _, _ in PROFILE_COLUMNS}
    for component in score.components:
        key = "places" if component.rule in _PLACES_RULES else component.rule
        if key in cells:
            cells[key] += component.points
    return cells


def driver_profile(season: Season, driver_id: Any) -> Profile | None:
    scored = season_scores(season)
    if not scored:
        return None

    driver = db.session.get(Driver, driver_id)
    if driver is None:
        return None

    rows: list[ProfileRow] = []
    totals = {key: Decimal(0) for key, _, _ in PROFILE_COLUMNS}
    grand = Decimal(0)
    team = None

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
            roster = roster_for_round(season, round_number)
            team = roster.team_for(driver_id)

    return Profile(
        subject=driver, team=team, kind="driver",
        rows=rows, totals=totals, grand_total=grand,
    )


def team_profile(season: Season, team_id: Any) -> Profile | None:
    """A team's season: both cars per round, and what the pick scored.

    Three columns plus the team's own figure. Showing the halves beside the sum
    makes the half-sum rule explain itself, which is the same trick the
    breakdown's "Half of Cassidy 9, Vergne 0" line does.
    """
    scored = season_scores(season)
    if not scored:
        return None

    team = db.session.get(Team, team_id)
    if team is None:
        return None

    car_ids: list = []
    rows: list[ProfileRow] = []
    car_rows: list = []
    grand = Decimal(0)

    for round_number in sorted(scored):
        round_obj, score = scored[round_number]
        roster = roster_for_round(season, round_number)
        cars = roster.drivers_by_team.get(team_id, [])
        for car in cars:
            if car not in car_ids:
                car_ids.append(car)

        team_total = engine.score_team(score, cars)
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

    roster = roster_for_round(season, min(scored))
    cars = [roster.drivers.get(c) for c in car_ids]

    car_totals = {
        car_id: sum((r["cars"].get(car_id, Decimal(0)) for r in car_rows), Decimal(0))
        for car_id in car_ids
    }

    return Profile(
        subject=team, team=team, kind="team",
        rows=rows, totals=car_totals, grand_total=grand,
        cars=[c for c in cars if c], car_rows=car_rows,
    )
