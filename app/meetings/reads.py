"""Reading stored scores back.

Phase 5's payoff. Everything that used to rescore on request now reads
`round_scores`, and the objects it hands back are shaped exactly like the ones
`app/scoring/engine.py` produces — same attributes, same methods, same
semantics. That is the whole design: the display code cannot tell the
difference, so turning the profiles and the meeting breakdown into reads
touched no template and no rendering logic.

`StoredRoundScores.drivers` holds **participants only**, mirroring
`engine.RoundScores.drivers`, while `score_for` returns a zero score for anyone
absent. That distinction is why `RoundScore.participated` exists as a stored
column rather than being inferred from an empty breakdown: a driver who raced
and scored nothing and a driver who was not there both have no components, and
a profile table that cannot tell them apart is showing a zero where it should
show a blank.

The rows for non-participants are still written, because a player may hold a
driver who has left the grid and a `PickScore` must always have a `RoundScore`
behind it. They are simply not part of the round's classification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.extensions import db
from app.models.calendar import Round, Season
from app.models.score import SUBJECT_TEAM, RoundScore
from app.scoring.engine import DriverRoundScore


@dataclass
class StoredRoundScores:
    """One round's stored scores, in the shape `engine.RoundScores` has.

    `issues` is always empty. The engine's issues describe a payload as it is
    being scored — a duel with three rows, a race with no lap times — and they
    belong to the run that produced them, which is the scoring pass's report
    and the worker's run record. Replaying them on every page view would show a
    reader a complaint about data they cannot act on.
    """

    drivers: dict[Any, DriverRoundScore] = field(default_factory=dict)
    teams: dict[Any, Decimal] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    def total_for(self, driver_id: Any) -> Decimal:
        """An absent driver scores zero. No substitution, no compensation."""
        score = self.drivers.get(driver_id)
        return score.total if score else Decimal(0)

    def score_for(self, driver_id: Any) -> DriverRoundScore:
        return self.drivers.get(driver_id) or DriverRoundScore(driver_id=driver_id)

    def team_total(self, team_id: Any) -> Decimal:
        """The stored half-sum, not a recomputation.

        Replaces `engine.score_team(scores, cars)` at every call site. The
        stored figure was computed against the round's own recorded ruleset;
        recomputing it here would use whichever divisor is current, which is
        exactly the silent rewrite of history that versioning exists to stop.
        """
        return self.teams.get(team_id, Decimal(0))

    @property
    def is_empty(self) -> bool:
        return not self.drivers and not self.teams


def _collect(rows) -> StoredRoundScores:
    scores = StoredRoundScores()
    for row in rows:
        if row.kind == SUBJECT_TEAM:
            scores.teams[row.team_id] = row.points
            continue
        if not row.participated:
            continue
        scores.drivers[row.driver_id] = DriverRoundScore(
            driver_id=row.driver_id,
            qualifying=row.qualifying_components,
            race=row.race_components,
        )
    return scores


def round_scores(round_obj: Round) -> StoredRoundScores:
    """One round's scores. Empty if the round has not been scored."""
    rows = db.session.scalars(
        select(RoundScore).where(RoundScore.round_id == round_obj.id)
    )
    return _collect(rows)


def meeting_scores(meeting) -> dict[int, StoredRoundScores]:
    """Every round of one meeting, keyed by round number, in one query."""
    round_ids = {r.id: r.round_number for r in meeting.rounds}
    if not round_ids:
        return {}

    rows = db.session.scalars(
        select(RoundScore).where(RoundScore.round_id.in_(round_ids))
    )
    grouped: dict[int, list] = {}
    for row in rows:
        grouped.setdefault(round_ids[row.round_id], []).append(row)
    return {number: _collect(rows) for number, rows in grouped.items()}


def season_scores(season: Season) -> dict[int, tuple[Round, StoredRoundScores]]:
    """Every scored round of a season, in one query.

    This is what `season_scores` in `scoring_bridge` used to do by rescoring
    seventeen rounds on every profile view — loading roughly nine hundred
    result rows and running the engine over all of them to render one column of
    one table. It is now one indexed read of the rows the pass already wrote.
    """
    stmt = (
        select(RoundScore, Round)
        .join(Round, RoundScore.round_id == Round.id)
        .where(RoundScore.season_id == season.id)
        .order_by(Round.round_number)
    )

    rounds: dict[int, Round] = {}
    grouped: dict[int, list] = {}
    for score, round_obj in db.session.execute(stmt):
        rounds[round_obj.round_number] = round_obj
        grouped.setdefault(round_obj.round_number, []).append(score)

    return {
        number: (rounds[number], _collect(rows))
        for number, rows in grouped.items()
    }
