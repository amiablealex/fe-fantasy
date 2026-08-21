"""The pickable grid for one round.

Moved here from `app/styleguide/scoring_bridge.py` in Phase 4. It was fine
there while the proof screens were its only caller, but the lineup service is
production code and the styleguide blueprint is registered only when
`app.debug` is true — a production module importing from a debug-only package
is a dependency pointing the wrong way, and it would break the day the
styleguide is deleted.

`scoring_bridge` now imports these names from here, so nothing it does changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.calendar import Season
from app.models.grid import Driver, SeatEntry, Team


def seat_entries(season: Season) -> list[SeatEntry]:
    stmt = (
        select(SeatEntry)
        .where(SeatEntry.season_id == season.id)
        .options(joinedload(SeatEntry.driver), joinedload(SeatEntry.team))
    )
    return list(db.session.scalars(stmt).unique())


@dataclass(frozen=True)
class Roster:
    """The pickable grid for one round.

    Which team a driver belongs to is a per-round question (SPEC.md §2): a
    mid-season switch produces two seat entries with disjoint round arrays, so
    the one-driver-per-team constraint is only correct when it is asked about a
    specific round. Season 12 contained no switches, so this path meets reality
    for the first time in Season 13.
    """

    team_of_driver: dict[Any, Any]
    drivers_by_team: dict[Any, list[Any]]
    drivers: dict[Any, Driver]
    teams: dict[Any, Team]
    rounds_participated: dict[Any, int]

    def team_for(self, driver_id: Any) -> Team | None:
        return self.teams.get(self.team_of_driver.get(driver_id))


def roster_for_round(season: Season, round_number: int) -> Roster:
    team_of_driver: dict[Any, Any] = {}
    drivers_by_team: dict[Any, list[Any]] = {}
    drivers: dict[Any, Driver] = {}
    teams: dict[Any, Team] = {}
    rounds_participated: dict[Any, int] = {}

    for seat in seat_entries(season):
        drivers[seat.driver_id] = seat.driver
        teams[seat.team_id] = seat.team
        rounds_participated[seat.driver_id] = seat.rounds_participated
        if not seat.covers_round(round_number):
            continue
        team_of_driver[seat.driver_id] = seat.team_id
        drivers_by_team.setdefault(seat.team_id, []).append(seat.driver_id)

    return Roster(
        team_of_driver=team_of_driver,
        drivers_by_team=drivers_by_team,
        drivers=drivers,
        teams=teams,
        rounds_participated=rounds_participated,
    )
