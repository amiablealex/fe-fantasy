"""Lineup rules: validity, transfer cost, and the dream team.

Pure, like the rest of `app/scoring/`. Phase 4 builds the editor on top of this
and Phase 2b's simulation needs valid-lineup enumeration, so the rules live in
one place that neither Flask nor SQLAlchemy can reach.

The central idea from SPEC.md §5: a lineup is a **snapshot**, and the transfer
allowance is a validation rule *between* consecutive snapshots rather than
stored truth. Everything below follows from that.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations, product
from typing import Any, Callable, Iterable, Mapping, Sequence

DRIVER_SLOTS = 4
TEAM_SLOTS = 1
TOTAL_SLOTS = DRIVER_SLOTS + TEAM_SLOTS

MAX_BANKED_TRANSFERS = 2


class LineupError(ValueError):
    """A lineup that breaks a structural rule."""


@dataclass(frozen=True)
class Lineup:
    """Four drivers and one team.

    Drivers are a frozenset: the four slots are interchangeable, and treating
    them as ordered would make a reordering look like four transfers.
    """

    drivers: frozenset
    team_id: Any

    @classmethod
    def of(cls, drivers: Iterable[Any], team_id: Any) -> "Lineup":
        drivers = frozenset(drivers)
        if len(drivers) != DRIVER_SLOTS:
            raise LineupError(
                f"A lineup needs {DRIVER_SLOTS} distinct drivers, got {len(drivers)}."
            )
        return cls(drivers=drivers, team_id=team_id)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Lineup drivers={sorted(map(str, self.drivers))} team={self.team_id}>"


@dataclass(frozen=True)
class LineupProblem:
    code: str
    message: str


PROBLEM_DRIVER_COUNT = "driver_count"
PROBLEM_DUPLICATE_TEAM = "duplicate_team"
PROBLEM_TEAM_ALREADY_REPRESENTED = "team_already_represented"
PROBLEM_UNKNOWN_DRIVER = "unknown_driver"


def validate_lineup(
    lineup: Lineup, team_of_driver: Mapping[Any, Any]
) -> list[LineupProblem]:
    """Check a lineup against the two structural rules.

    `team_of_driver` maps driver to team **for the round in question**. That is
    not a detail: a mid-season transfer means a driver's team changes, so the
    one-driver-per-team constraint has to be evaluated against the seat they
    held at that meeting, not the seat they hold now.

    Returns a list of problems; empty means valid.
    """
    problems: list[LineupProblem] = []

    if len(lineup.drivers) != DRIVER_SLOTS:
        problems.append(LineupProblem(
            PROBLEM_DRIVER_COUNT,
            f"Pick {DRIVER_SLOTS} drivers; you have {len(lineup.drivers)}.",
        ))

    teams: dict[Any, list[Any]] = {}
    for driver_id in lineup.drivers:
        if driver_id not in team_of_driver:
            problems.append(LineupProblem(
                PROBLEM_UNKNOWN_DRIVER,
                f"Driver {driver_id} has no seat for this round.",
            ))
            continue
        teams.setdefault(team_of_driver[driver_id], []).append(driver_id)

    for team_id, drivers in teams.items():
        if len(drivers) > 1:
            problems.append(LineupProblem(
                PROBLEM_DUPLICATE_TEAM,
                f"Only one driver per team; you have {len(drivers)} from {team_id}.",
            ))

    if lineup.team_id in teams:
        problems.append(LineupProblem(
            PROBLEM_TEAM_ALREADY_REPRESENTED,
            f"Your team pick {lineup.team_id} is already represented by a driver.",
        ))

    return problems


def is_valid(lineup: Lineup, team_of_driver: Mapping[Any, Any]) -> bool:
    return not validate_lineup(lineup, team_of_driver)


# -----------------------------------------------------------------------------
# Transfers
# -----------------------------------------------------------------------------


def transfer_cost(previous: Lineup | None, current: Lineup) -> int:
    """The number of changed slots between consecutive snapshots.

    That is the whole rule. Count the drivers who came in, add one if the team
    pick moved.

    It gives the forced-relocation case the right answer without a special case:
    bringing in a driver from the team currently occupying your team slot forces
    the team slot to move as well, two slots change, so the move costs two and is
    unavailable until two transfers are banked. There is no partial version.

    No previous snapshot means the first lineup of the season, which is free.
    """
    if previous is None:
        return 0
    incoming = current.drivers - previous.drivers
    cost = len(incoming)
    if current.team_id != previous.team_id:
        cost += TEAM_SLOTS
    return cost


def transfers_available(
    used_by_meeting: Sequence[int], allowance_per_meeting: int = 1
) -> int:
    """Transfers in hand after a run of meetings.

    One per meeting, banking to a maximum of two. Derived from the snapshot
    history rather than stored, so it can never drift out of step with the
    lineups it describes.
    """
    available = 0
    for used in used_by_meeting:
        available = min(available + allowance_per_meeting, MAX_BANKED_TRANSFERS)
        available -= used
        if available < 0:
            raise LineupError(
                f"Transfer history is impossible: {used} spent with "
                f"{available + used} available."
            )
    return min(available + allowance_per_meeting, MAX_BANKED_TRANSFERS)


def change_is_affordable(
    previous: Lineup | None, current: Lineup, available: int
) -> bool:
    return transfer_cost(previous, current) <= available


# -----------------------------------------------------------------------------
# Enumeration and the dream team
# -----------------------------------------------------------------------------


def valid_lineups(drivers_by_team: Mapping[Any, Sequence[Any]]):
    """Yield every valid lineup over the given roster.

    Derived entirely from the roster passed in — the grid size is never assumed.
    At ten teams of two that is C(10,4) x 2^4 x 6 = 20,160 lineups, which is
    instant; if Gen4 brings an eleventh team or a third car, this simply yields
    more.
    """
    team_ids = list(drivers_by_team)
    for driver_teams in combinations(team_ids, DRIVER_SLOTS):
        remaining = [t for t in team_ids if t not in driver_teams]
        if not remaining:
            continue
        for picks in product(*(drivers_by_team[t] for t in driver_teams)):
            for team_id in remaining:
                yield Lineup(drivers=frozenset(picks), team_id=team_id)


def count_valid_lineups(drivers_by_team: Mapping[Any, Sequence[Any]]) -> int:
    """Closed-form count, for a sanity check that does not enumerate."""
    from math import comb

    team_ids = list(drivers_by_team)
    n_teams = len(team_ids)
    if n_teams <= DRIVER_SLOTS:
        return 0
    total = 0
    for driver_teams in combinations(team_ids, DRIVER_SLOTS):
        seats = 1
        for team_id in driver_teams:
            seats *= len(drivers_by_team[team_id])
        total += seats * (n_teams - DRIVER_SLOTS)
    return total


@dataclass(frozen=True)
class DreamTeam:
    total: Decimal
    lineups: tuple[Lineup, ...]

    @property
    def is_tied(self) -> bool:
        return len(self.lineups) > 1

    @property
    def best(self) -> Lineup:
        return self.lineups[0]


def dream_team(
    drivers_by_team: Mapping[Any, Sequence[Any]],
    driver_score: Callable[[Any], Decimal],
    team_score: Callable[[Any], Decimal],
    *,
    keep_all_ties: bool = True,
) -> DreamTeam:
    """The highest-scoring valid lineup, brute-forced.

    No optimisation: 20,160 combinations is nothing, and an exact answer that is
    obviously correct beats a clever one that might not be.

    Ties are collected rather than broken. A high tie rate is a signal the
    scoring gradient is too coarse, which is question 7 of the Season 12
    simulation — so throwing ties away would discard the measurement.
    """
    best_total: Decimal | None = None
    best: list[Lineup] = []

    driver_cache: dict[Any, Decimal] = {}
    for team_drivers in drivers_by_team.values():
        for driver_id in team_drivers:
            driver_cache[driver_id] = Decimal(driver_score(driver_id))
    team_cache = {team_id: Decimal(team_score(team_id)) for team_id in drivers_by_team}

    for lineup in valid_lineups(drivers_by_team):
        total = team_cache[lineup.team_id]
        for driver_id in lineup.drivers:
            total += driver_cache[driver_id]

        if best_total is None or total > best_total:
            best_total = total
            best = [lineup]
        elif keep_all_ties and total == best_total:
            best.append(lineup)

    return DreamTeam(total=best_total or Decimal(0), lineups=tuple(best))
