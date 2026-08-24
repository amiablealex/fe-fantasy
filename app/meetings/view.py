"""View models: a lineup, a meeting, and what it scored.

The fourth of the modules `scoring_bridge` became, and the only one that takes a
lineup. It turns stored scores plus five picks into the objects
`_lineup.html` consumes in its `scored` state, and it computes the Perfect Five.

Nothing here scores anything. `RoundScore` already holds the truth; this reads
it, projects it onto a player's picks, and adds the two things no stored score
answers: which rules fired in which contest, and what actually happened on
track.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.lineups.roster import Roster, roster_for_round, seat_entries
from app.meetings import display
from app.meetings.bridge import round_payload
from app.meetings.reads import meeting_scores
from app.models.calendar import Meeting, Round, Season
from app.models.grid import Team
from app.scoring import lineups

ZERO = Decimal(0)


def marked_drivers(lineup: lineups.Lineup | None, meeting: Meeting) -> frozenset:
    """Every driver in a results table that fed a lineup: six, not four.

    The four driver picks, plus both cars of the team pick — because the team
    slot scores half the sum of its two drivers, so those rows are as much a
    part of the figure above them as the four are. One rule across the whole
    application: **the mark means this row fed the score you are looking at.**

    Which makes it correct on a friend's profile as well as your own. The mark
    belongs to the lineup rendered directly above it, whoever's lineup that is.

    The roster resolves against the meeting's first round, which is the round
    the lineup was locked against.
    """
    if lineup is None or not meeting.rounds:
        return frozenset()
    first = min(r.round_number for r in meeting.rounds)
    roster = roster_for_round(meeting.season, first)
    cars = roster.drivers_by_team.get(lineup.team_id, [])
    return frozenset(lineup.drivers) | frozenset(cars)


# -----------------------------------------------------------------------------
# One round
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


# -----------------------------------------------------------------------------
# One slot, for one round
# -----------------------------------------------------------------------------
#
# Extracted in Phase 8.3c, when a driver tapped in a classification needed the
# same card a lineup slot gives. Building a second copy of these two would have
# been the "a read written twice is a read that will disagree" defect §11
# already records: the two would have drifted on the first wording change, and
# the same driver would then read differently depending on where you tapped
# them, which is precisely the failure the card exists to prevent.


def _driver_pick(roster, scores, qualifying, race_rows, driver_id) -> PickScore:
    driver = roster.drivers.get(driver_id)
    score = scores.score_for(driver_id)
    return PickScore(
        kind="driver",
        label=driver.short_label if driver else str(driver_id),
        subject=driver,
        team=roster.team_for(driver_id),
        total=score.total,
        components=score.components,
        # Read from the results rather than from the score: "started P13,
        # finished P5" is what happened, which is a different question from what
        # scored, and no stored score answers it.
        quali_context=display.qualifying_context(qualifying, driver_id),
        race_context=display.race_context(race_rows, driver_id),
    )


def _team_pick(roster, scores, team_id) -> PickScore:
    team = roster.teams.get(team_id)
    cars = roster.drivers_by_team.get(team_id, [])
    car_detail = ", ".join(
        f"{roster.drivers[c].short_label} {display.fmt(scores.total_for(c))}"
        for c in sorted(cars, key=lambda c: -scores.total_for(c))
        if c in roster.drivers
    )
    return PickScore(
        kind="team",
        label=(team.name if team else str(team_id)),
        subject=team,
        team=team,
        total=scores.team_total(team_id),
        components=(),
        detail=car_detail,
    )


def score_meeting(
    season: Season, meeting: Meeting, lineup: lineups.Lineup
) -> list[RoundBreakdown]:
    """Read one lineup's scores across every round of a meeting.

    A double-header scores the same lineup twice, which is the whole reason the
    meeting is the transfer unit and the round is the scoring unit.
    """
    breakdowns: list[RoundBreakdown] = []
    # One seat query and one score query for the whole meeting, rather than one
    # of each per round.
    seats = seat_entries(season)
    stored = meeting_scores(meeting)

    for round_obj in sorted(meeting.rounds, key=lambda r: r.round_number):
        scores = stored.get(round_obj.round_number)
        if scores is None or scores.is_empty:
            breakdowns.append(RoundBreakdown(
                round=round_obj, picks=[], total=ZERO,
                dream_total=ZERO, dream_tied=0,
                issues=["not scored yet"], scored=False,
            ))
            continue

        # Results are still read, for the context line under each pick.
        # "Started P13, finished P5" describes what happened, which is a
        # different question from what scored, and no stored score answers it.
        qualifying, race_rows = round_payload(round_obj)
        roster = roster_for_round(season, round_obj.round_number, seats=seats)

        # No star is decided here. This used to brute-force a per-round legal
        # dream team — 20,160 combinations on every page view — and every
        # production caller then threw the answer away by calling `mark_best`
        # with the meeting-level Perfect Five. Worse than wasted: the one caller
        # that forgot to overwrite it rendered per-round stars against a
        # meeting-level total, so two of five slots starred and three did not.
        # A star is a fact about the meeting, so only `mark_best` sets one.
        picks: list[PickScore] = [
            _driver_pick(roster, scores, qualifying, race_rows, driver_id)
            for driver_id in sorted(
                lineup.drivers, key=lambda d: -scores.total_for(d)
            )
        ]
        picks.append(_team_pick(roster, scores, lineup.team_id))

        breakdowns.append(RoundBreakdown(
            round=round_obj,
            picks=picks,
            total=sum((p.total for p in picks), ZERO),
            dream_total=ZERO,
            dream_tied=0,
            issues=scores.issues,
        ))

    return breakdowns


# -----------------------------------------------------------------------------
# A whole meeting
# -----------------------------------------------------------------------------


@dataclass
class RoundDetail:
    """One round's contribution to one pick, split the way a reader wants it.

    Qualifying and race are kept apart rather than concatenated because they are
    separate contests with separate ceilings — 8 against 17 — and merging them
    hides which half of the weekend went well.
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
    breakdown discloses on tap: a double-header's 21 is 12 and 9, and the reader
    asks for that rather than being shown it.
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


def _slot_key(pick) -> tuple:
    """What makes two per-round picks the same slot.

    Keyed on the subject's identity rather than its label. Two drivers sharing a
    surname would render the same `short_label`, and keying on that would fold
    both into one slot and silently double one figure while dropping the other.
    The label is only a fallback for a pick whose subject has gone missing, and
    there the collision is already visible.
    """
    subject_id = getattr(pick.subject, "id", None)
    return (pick.kind, subject_id if subject_id is not None else pick.label)


def aggregate_meeting(breakdowns: list[RoundBreakdown]) -> list[PickMeetingScore]:
    """Collapse per-round breakdowns into one entry per slot.

    Slot order is preserved from the first scored round rather than re-sorted by
    score: the lineup is a fixed arrangement the player learns, and a layout that
    reshuffles by performance would make it unreadable at a glance.
    """
    scored = [b for b in breakdowns if b.scored]
    if not scored:
        return []

    order = [_slot_key(p) for p in scored[0].picks]
    aggregated: dict[tuple, PickMeetingScore] = {}

    for breakdown in scored:
        for pick in breakdown.picks:
            key = _slot_key(pick)
            entry = aggregated.get(key)
            if entry is None:
                entry = PickMeetingScore(
                    kind=pick.kind,
                    label=pick.label,
                    subject=pick.subject,
                    team=pick.team,
                    total=ZERO,
                    rounds=[],
                    detail=pick.detail,
                    number=getattr(pick.subject, "number", None),
                )
                aggregated[key] = entry

            qualifying, race = display.split_components(pick.components)

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


def subject_meeting_score(
    season: Season, meeting: Meeting, kind: str, subject_id: Any
) -> PickMeetingScore | None:
    """One driver or one team, scored across a meeting, in the pick shape.

    The same object a lineup slot discloses, for a subject nobody necessarily
    picked. It exists because a driver's name in a classification used to open
    their whole season, which answers a question the reader did not ask: they
    tapped a row inside a specific weekend.

    **Meeting-scoped, not round-scoped**, even though the tap happened inside
    one round's classification. A double-header would otherwise give the same
    driver two different cards depending on which round's table you came from,
    with nothing on either saying which — and the lineup slot above it would
    show a third figure, the sum. One card per subject per weekend, and the
    round you came from is a section inside it.

    Built by handing `aggregate_meeting` a breakdown holding a single pick,
    which is why there is no aggregation logic here: a card and a slot are the
    same shape because they are the same function.
    """
    seats = seat_entries(season)
    stored = meeting_scores(meeting)
    breakdowns: list[RoundBreakdown] = []

    for round_obj in sorted(meeting.rounds, key=lambda r: r.round_number):
        scores = stored.get(round_obj.round_number)
        if scores is None or scores.is_empty:
            continue

        roster = roster_for_round(season, round_obj.round_number, seats=seats)
        if kind == "driver":
            if subject_id not in roster.drivers:
                continue
            qualifying, race_rows = round_payload(round_obj)
            pick = _driver_pick(
                roster, scores, qualifying, race_rows, subject_id
            )
        elif kind == "team":
            if subject_id not in roster.teams:
                continue
            pick = _team_pick(roster, scores, subject_id)
        else:
            return None

        breakdowns.append(RoundBreakdown(
            round=round_obj,
            picks=[pick],
            total=pick.total,
            dream_total=ZERO,
            dream_tied=0,
            issues=scores.issues,
        ))

    picks = aggregate_meeting(breakdowns)
    return picks[0] if picks else None

# -----------------------------------------------------------------------------
# The Perfect Five — the five best picks of a weekend
# -----------------------------------------------------------------------------


@dataclass
class BestLineup:
    lineup: lineups.Lineup | None
    total: Decimal
    tied: int


def _meeting_totals(season: Season, meeting: Meeting):
    """Driver and team scores summed across a meeting, plus best finish.

    The finishing position is carried for the tiebreak below. It is read from
    the race classification rather than from a stored score because no stored
    score answers "where did they come" — that is `Result`'s question.
    """
    stored = meeting_scores(meeting)
    seats = seat_entries(season)

    driver_totals: dict[Any, Decimal] = {}
    team_totals: dict[Any, Decimal] = {}
    best_finish: dict[Any, int] = {}
    roster: Roster | None = None

    for round_obj in sorted(meeting.rounds, key=lambda r: r.round_number):
        scores = stored.get(round_obj.round_number)
        if scores is None or scores.is_empty:
            continue
        roster = roster_for_round(season, round_obj.round_number, seats=seats)

        for driver_id in roster.team_of_driver:
            driver_totals[driver_id] = (
                driver_totals.get(driver_id, ZERO) + scores.total_for(driver_id)
            )
        for team_id in roster.drivers_by_team:
            team_totals[team_id] = (
                team_totals.get(team_id, ZERO) + scores.team_total(team_id)
            )

        _, race_rows = round_payload(round_obj)
        for row in race_rows:
            position = row.get("position")
            driver_id = row.get("driver_id")
            if position is None or driver_id is None:
                continue
            current = best_finish.get(driver_id)
            if current is None or position < current:
                best_finish[driver_id] = position

    return roster, driver_totals, team_totals, best_finish


# A driver who did not finish anywhere sorts behind everyone who did, without
# needing a branch in the sort key.
_UNPLACED = 10**6


def meeting_best_lineup(season: Season, meeting: Meeting) -> BestLineup:
    """The four best-scoring drivers and the best-scoring team.

    **Deliberately not the best *valid* lineup.** An earlier version brute-forced
    every legal combination, which produced a page a reader could not parse: a
    driver who outscored three of the five was absent because a higher-scoring
    team-mate had taken his team's slot, and no caption fixes that — you have to
    hold the constraint set in your head to understand why. It also tied
    constantly, on six of seventeen Season 12 rounds and across as many as
    eighteen lineups, so "this is the answer" was rarely true.

    What is lost is a benchmark: this is not a lineup anybody could have
    fielded, and the page says so in a sentence. What is gained is that the star
    on a pick now means one simple thing — it was one of the five best picks of
    the weekend.

    Scored across the whole meeting rather than per round, because a
    double-header scores one lineup twice and the question is which picks
    maximise the sum.

    **The order is total, then the driver's best finishing position, then the
    id.** Two drivers cannot share a finishing position, so the second key
    settles every tie the first leaves and ties cannot reach the page at all.
    The third exists only so a driver who never finished still sorts
    deterministically — `seat_entries()` has no `ORDER BY`, and before this the
    winner of a tie could differ between two requests for the same weekend,
    which is exactly what made a starred pick sometimes fail to appear here.

    `dream_team` and `valid_lineups` stay in `app/scoring/lineups.py`: the
    Season 12 simulation measures the tie rate over legal lineups (SPEC.md §9,
    question 7) and that is still the right question to ask there.
    """
    roster, driver_totals, team_totals, best_finish = _meeting_totals(season, meeting)
    if roster is None or not driver_totals or not team_totals:
        return BestLineup(None, ZERO, 0)

    ranked = sorted(
        driver_totals,
        key=lambda d: (-driver_totals[d], best_finish.get(d, _UNPLACED), str(d)),
    )
    if len(ranked) < lineups.DRIVER_SLOTS:
        return BestLineup(None, ZERO, 0)
    drivers = ranked[:lineups.DRIVER_SLOTS]

    def team_finish(team_id: Any) -> int:
        cars = roster.drivers_by_team.get(team_id, [])
        return min((best_finish.get(c, _UNPLACED) for c in cars), default=_UNPLACED)

    team_id = min(
        team_totals,
        key=lambda t: (-team_totals[t], team_finish(t), str(t)),
    )

    total = sum((driver_totals[d] for d in drivers), ZERO) + team_totals[team_id]

    # A `Lineup` even though the picks need not form a legal one: `Lineup.of`
    # checks only that there are four distinct drivers, and returning the same
    # type keeps every caller — the shim, the friend profile, the styleguide —
    # working unchanged.
    return BestLineup(
        lineup=lineups.Lineup.of(drivers, team_id), total=total, tied=1
    )


def mark_best(picks: list[PickMeetingScore], best: lineups.Lineup | None) -> None:
    """Star the picks that were among the five best of the weekend.

    Per-round stars would contradict a meeting-level total: a driver can be one
    of round 7's best five and not round 8's, and a single star against a
    combined figure has to mean one thing.

    **Compared within kind, never against one merged set.** Drivers and teams
    are separate tables with independent primary key sequences, so at this grid
    size driver 4 and team 4 are the same integer — and an earlier version
    tested every pick against `set(best.drivers) | {best.team_id}`, which
    starred any driver whose id collided with the best team's. It presented as
    a star on a pick that was nowhere near the Perfect Five, intermittently,
    depending on whether the collision landed on a driver anyone held.
    """
    drivers = set(best.drivers) if best else set()
    team_id = best.team_id if best else None
    for pick in picks:
        subject_id = getattr(pick.subject, "id", None)
        if subject_id is None:
            pick.in_dream_team = False
        elif pick.is_team:
            pick.in_dream_team = subject_id == team_id
        else:
            pick.in_dream_team = subject_id in drivers
