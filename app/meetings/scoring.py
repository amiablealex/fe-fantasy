"""The scoring pass.

Turns ingested results into stored scores. Runs as its own pass rather than
inside the ingest, for three reasons: a round is not scoreable until several
sessions have landed, so scoring inside the ingest would be nine no-ops and a
tenth that does everything; the pass has to be runnable without re-fetching,
which is what makes a bug fix cheap; and the two want different transaction
boundaries — the ingest commits per session, this commits per round.

It cannot live in `app/scoring/`. A test asserts that package imports neither
Flask nor SQLAlchemy so `sim/` can run without a web application, and this
module is nothing but database work. `app/scoring/` decides what a result is
worth; this decides what to write down.

Partial scoring, deliberately
-----------------------------
Qualifying finishes hours before the race. The pass scores whatever has landed
and marks the round provisional until every session it has is in.

That is safe because of a property of the rules rather than of the code: every
fantasy point is additive within a session, and places gained/lost — the one
rule that can go negative — needs the race and therefore lands atomically with
it. So a provisional score is a **monotonically increasing partial sum**. It
never revises downward. "Qualifying 8, race to come" is an honest sentence in a
way that a figure which might drop later would not be.

The one thing that can move a stored score down is the provider correcting a
classification, and that is a correction we want.

What makes a round complete
---------------------------
Its race results are in, and every scoring session it holds has been ingested.
Deliberately not "and the bracket has the expected ten sessions": the sync
already raises `unexpected_session_shape` on a completed round with the wrong
count (SPEC.md §6), and a second copy of that expectation living here is how
the two quietly disagree. If the race has landed, the weekend has run, and the
qualifying schedule is not going to grow.

Idempotence
-----------
Scoring is a pure function of the ingested results and the round's recorded
ruleset, so the pass deletes the round's scores and rewrites them inside one
transaction rather than upserting. Delete-and-rewrite is the only version that
cannot leave a stale row behind — including a row for a driver who has since
dropped out of a corrected classification, which an upsert would preserve
forever.

Idempotent means same inputs, same outputs. It does not mean numbers never
move: a corrected classification legitimately rescores, and should.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.lineups.roster import roster_for_round, seat_entries
from app.lineups.service import effective_snapshots
from app.meetings.scoring_bridge import round_payload, ruleset_for
from app.models.calendar import SCORING_STAGES, STAGE_RACE, Round, Season, Session
from app.models.lineup import PICK_DRIVER, LineupSnapshot
from app.models.score import (
    SUBJECT_DRIVER,
    SUBJECT_TEAM,
    PickScore,
    RoundScore,
    breakdown_from,
)
from app.scoring import engine

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# -----------------------------------------------------------------------------
# Completeness and the dirty check
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Completeness:
    """How much of a round has been ingested."""

    expected: int      # scoring sessions the round holds
    ingested: int      # of those, how many have results
    has_race: bool

    @property
    def any_results(self) -> bool:
        return self.ingested > 0

    @property
    def complete(self) -> bool:
        return self.has_race and self.expected > 0 and self.ingested == self.expected

    @property
    def provisional(self) -> bool:
        return not self.complete

    @property
    def missing(self) -> int:
        return self.expected - self.ingested

    def describe(self) -> str:
        if self.complete:
            return f"{self.ingested} sessions"
        return f"{self.ingested} of {self.expected} sessions, provisional"


def completeness(round_obj: Round) -> Completeness:
    sessions = [s for s in round_obj.sessions if s.stage in SCORING_STAGES]
    ingested = [s for s in sessions if s.results_ingested_at is not None]
    return Completeness(
        expected=len(sessions),
        ingested=len(ingested),
        has_race=any(s.stage == STAGE_RACE for s in ingested),
    )


def last_ingest_at(round_obj: Round) -> datetime | None:
    stamps = [
        s.results_ingested_at
        for s in round_obj.sessions
        if s.results_ingested_at is not None
    ]
    return max(stamps) if stamps else None


def needs_scoring(round_obj: Round) -> bool:
    """Whether the pass has anything to do for this round.

    Results-driven and nothing else. A lineup cannot invalidate a stored score:
    a snapshot may only be committed for the *open* meeting (SPEC.md §2), so by
    the time a round has run, every lineup that scores against it is already
    fixed. That is what makes the per-user `PickScore` rows safe to
    materialise — nothing a player does after the deadline can make them wrong.

    This is the gate the poller checks on every tick, so it must stay free of
    queries: it reads only what the caller has already loaded.
    """
    latest = last_ingest_at(round_obj)
    if latest is None:
        return False
    if round_obj.scored_at is None:
        return True
    return round_obj.scored_at < latest


# -----------------------------------------------------------------------------
# Reports
# -----------------------------------------------------------------------------


@dataclass
class RoundOutcome:
    round_number: int
    scored: bool
    provisional: bool = False
    round_scores: int = 0
    pick_scores: int = 0
    reason: str | None = None
    issues: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if not self.scored:
            return f"R{self.round_number}: skipped ({self.reason})"
        state = " provisional" if self.provisional else ""
        return (
            f"R{self.round_number}: {self.round_scores} scores, "
            f"{self.pick_scores} picks{state}"
        )


@dataclass
class ScoringReport:
    season_year: int
    rounds_considered: int = 0
    rounds_scored: int = 0
    rounds_provisional: int = 0
    round_scores: int = 0
    pick_scores: int = 0
    outcomes: list[RoundOutcome] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return (
            f"season {self.season_year}: "
            f"{self.rounds_scored} of {self.rounds_considered} rounds scored "
            f"({self.rounds_provisional} provisional), "
            f"{self.round_scores} round scores, {self.pick_scores} pick scores, "
            f"{len(self.warnings)} warnings, {len(self.errors)} errors"
        )


# -----------------------------------------------------------------------------
# One round
# -----------------------------------------------------------------------------


def _picked_subjects(snapshots: list[LineupSnapshot]) -> tuple[set, set]:
    drivers, teams = set(), set()
    for snapshot in snapshots:
        for pick in snapshot.picks:
            if pick.kind == PICK_DRIVER:
                drivers.add(pick.driver_id)
            else:
                teams.add(pick.team_id)
    return drivers, teams


def score_round(
    round_obj: Round,
    *,
    seats: list | None = None,
    snapshots: list[LineupSnapshot] | None = None,
) -> RoundOutcome:
    """Score one round and commit.

    Commits rather than leaving it to the caller, matching the per-session
    pattern in `app/ingest/results.py`: one bad round must not abandon the
    rest of the season, and a rollback has to be able to undo exactly this
    round's writes.
    """
    outcome = RoundOutcome(round_number=round_obj.round_number, scored=False)

    state = completeness(round_obj)
    if not state.any_results:
        outcome.reason = "no results ingested"
        return outcome

    ruleset = ruleset_for(round_obj)
    qualifying, race_rows = round_payload(round_obj)
    scores = engine.score_round(qualifying, race_rows, ruleset=ruleset)
    outcome.issues = list(scores.issues)

    roster = roster_for_round(round_obj.season, round_obj.round_number, seats=seats)
    if snapshots is None:
        snapshots = effective_snapshots(round_obj.meeting)
    picked_drivers, picked_teams = _picked_subjects(snapshots)

    # Three sources, unioned. The roster gives everyone who could be picked —
    # including a driver who never appeared in the classification, who scores a
    # real zero rather than being absent from the table. Results add anyone who
    # raced without a seat entry, so the results pages have a row to read. And
    # the picks add anyone a player still holds who has since left the grid,
    # because §2 says that pick scores 0 and costs a normal transfer, and a
    # PickScore with no RoundScore behind it would be a number with no
    # derivation.
    driver_ids = set(roster.team_of_driver) | set(scores.drivers) | picked_drivers
    team_ids = set(roster.drivers_by_team) | picked_teams
    driver_ids.discard(None)
    team_ids.discard(None)

    now = _utcnow()

    # Delete both, in dependency order, before writing either. `PickScore`
    # would cascade from `RoundScore` anyway, but relying on that would make
    # the wipe invisible to anyone reading this function.
    db.session.execute(delete(PickScore).where(PickScore.round_id == round_obj.id))
    db.session.execute(delete(RoundScore).where(RoundScore.round_id == round_obj.id))
    db.session.flush()

    rows: dict[tuple[str, Any], RoundScore] = {}

    for driver_id in sorted(driver_ids):
        score = scores.score_for(driver_id)
        rows[(SUBJECT_DRIVER, driver_id)] = RoundScore(
            season_id=round_obj.season_id,
            round_id=round_obj.id,
            kind=SUBJECT_DRIVER,
            driver_id=driver_id,
            points=score.total,
            breakdown=breakdown_from(score.qualifying, score.race),
            # The engine returns a driver only if they appeared in qualifying
            # or the race, so membership here is exactly participation — and
            # it stays right for someone who took part and scored nothing.
            participated=driver_id in scores.drivers,
            ruleset_version=ruleset.version,
            scored_at=now,
        )

    for team_id in sorted(team_ids):
        cars = sorted(roster.drivers_by_team.get(team_id, []))
        rows[(SUBJECT_TEAM, team_id)] = RoundScore(
            season_id=round_obj.season_id,
            round_id=round_obj.id,
            kind=SUBJECT_TEAM,
            team_id=team_id,
            points=engine.score_team(scores, cars, ruleset=ruleset),
            # A team's score is an arithmetic consequence of its drivers'
            # rather than a set of rules in its own right, so there is no
            # breakdown. The cars are stored instead, which is what makes the
            # half-sum rule explain itself on the page.
            breakdown=[],
            detail={"cars": [[car, str(scores.total_for(car))] for car in cars]},
            # A team took part if it had cars on the grid this round.
            participated=bool(cars),
            ruleset_version=ruleset.version,
            scored_at=now,
        )

    db.session.add_all(rows.values())
    db.session.flush()

    for snapshot in snapshots:
        if not snapshot.is_complete:
            outcome.issues.append(
                f"user {snapshot.user_id} has an incomplete snapshot; not scored"
            )
            continue
        for pick in snapshot.picks:
            key = (
                (SUBJECT_DRIVER, pick.driver_id)
                if pick.kind == PICK_DRIVER
                else (SUBJECT_TEAM, pick.team_id)
            )
            source = rows[key]
            db.session.add(PickScore(
                user_id=snapshot.user_id,
                season_id=round_obj.season_id,
                meeting_id=round_obj.meeting_id,
                round_id=round_obj.id,
                snapshot_id=snapshot.id,
                round_score_id=source.id,
                kind=source.kind,
                driver_id=source.driver_id,
                team_id=source.team_id,
                # Copied, not joined for. It is the column every league table
                # sums, and a denormalised number rewritten in the same
                # transaction as its source cannot drift.
                points=source.points,
                scored_at=now,
            ))
            outcome.pick_scores += 1

    round_obj.scored_at = now
    round_obj.scoring_provisional = state.provisional
    db.session.commit()

    outcome.scored = True
    outcome.provisional = state.provisional
    outcome.round_scores = len(rows)
    return outcome


# -----------------------------------------------------------------------------
# A season
# -----------------------------------------------------------------------------


def _rounds_for(season: Season, round_numbers: list[int] | None) -> list[Round]:
    stmt = (
        select(Round)
        .where(Round.season_id == season.id)
        .options(
            joinedload(Round.meeting),
            selectinload(Round.sessions).selectinload(Session.results),
        )
        .order_by(Round.round_number)
    )
    if round_numbers:
        stmt = stmt.where(Round.round_number.in_(round_numbers))
    return list(db.session.scalars(stmt).unique())


def score_season(
    season: Season,
    *,
    force: bool = False,
    round_numbers: list[int] | None = None,
) -> ScoringReport:
    """Score every round of a season that has moved since it was last scored.

    `force` rescores regardless. It exists for a fixed bug in the engine, not
    for a re-tuned ruleset: a round records the version in force when it was
    created, so re-tuning after Jeddah changes how *future* rounds score and
    forcing a rescore would still reproduce the old numbers (SPEC.md §3).
    """
    report = ScoringReport(season_year=season.year)

    seats = seat_entries(season)
    snapshot_cache: dict[int, list[LineupSnapshot]] = {}

    for round_obj in _rounds_for(season, round_numbers):
        report.rounds_considered += 1

        if not force and not needs_scoring(round_obj):
            report.outcomes.append(RoundOutcome(
                round_number=round_obj.round_number,
                scored=False,
                reason="already scored, no new results",
            ))
            continue

        meeting_id = round_obj.meeting_id
        if meeting_id not in snapshot_cache:
            snapshot_cache[meeting_id] = effective_snapshots(round_obj.meeting)

        try:
            outcome = score_round(
                round_obj, seats=seats, snapshots=snapshot_cache[meeting_id]
            )
        except Exception as exc:
            db.session.rollback()
            message = f"R{round_obj.round_number}: {exc}"
            report.errors.append(message)
            log.exception("Scoring failed for %s", message)
            continue

        report.outcomes.append(outcome)
        if outcome.scored:
            report.rounds_scored += 1
            report.round_scores += outcome.round_scores
            report.pick_scores += outcome.pick_scores
            if outcome.provisional:
                report.rounds_provisional += 1
        for issue in outcome.issues:
            report.warnings.append(f"R{round_obj.round_number}: {issue}")

    log.info("Scoring complete: %s", report.summary())
    return report
