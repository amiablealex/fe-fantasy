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

        def team_total(team_id: Any) -> Decimal:
            return scores.team_total(team_id)

        dream = lineups.dream_team(
            roster.drivers_by_team, scores.total_for, team_total
        )
        dream_drivers: set = set()
        dream_teams: set = set()
        for candidate in dream.lineups:
            dream_drivers |= candidate.drivers
            dream_teams.add(candidate.team_id)

        picks: list[PickScore] = []
        for driver_id in sorted(lineup.drivers, key=lambda d: -scores.total_for(d)):
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
                quali_context=display.qualifying_context(qualifying, driver_id),
                race_context=display.race_context(race_rows, driver_id),
            ))

        team = roster.teams.get(lineup.team_id)
        cars = roster.drivers_by_team.get(lineup.team_id, [])
        car_detail = ", ".join(
            f"{roster.drivers[c].short_label} {display.fmt(scores.total_for(c))}"
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
            total=sum((p.total for p in picks), ZERO),
            dream_total=dream.total,
            dream_tied=len(dream.lineups),
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


# -----------------------------------------------------------------------------
# The Perfect Five — the best possible lineup for a meeting
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
    seats = seat_entries(season)

    stored = meeting_scores(meeting)

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

    if roster is None:
        return BestLineup(None, ZERO, 0)

    best = lineups.dream_team(
        roster.drivers_by_team,
        lambda d: driver_totals.get(d, ZERO),
        lambda t: team_totals.get(t, ZERO),
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
