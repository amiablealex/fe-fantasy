"""Lineup rule tests.

The transfer-cost cases are the ones worth reading. SPEC.md §2 settles that
cost is the count of changed slots and that a forced team relocation therefore
costs two, spent atomically — and the whole reason for storing snapshots rather
than deltas is that this stays derivable. If these tests are right, the transfer
bank can always be recomputed from history.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.scoring.lineups import (
    MAX_BANKED_TRANSFERS,
    PROBLEM_DRIVER_COUNT,
    PROBLEM_DUPLICATE_TEAM,
    PROBLEM_TEAM_ALREADY_REPRESENTED,
    PROBLEM_UNKNOWN_DRIVER,
    DreamTeam,
    Lineup,
    LineupError,
    change_is_affordable,
    count_valid_lineups,
    dream_team,
    is_valid,
    transfer_cost,
    transfers_available,
    valid_lineups,
    validate_lineup,
)

# Ten teams of two, matching the current grid without hard-coding it anywhere
# in the implementation.
GRID = {f"t{t}": (f"t{t}a", f"t{t}b") for t in range(1, 11)}
TEAM_OF_DRIVER = {d: t for t, drivers in GRID.items() for d in drivers}


def lineup(drivers, team):
    return Lineup.of(drivers, team)


# -----------------------------------------------------------------------------
# Structure
# -----------------------------------------------------------------------------


def test_a_lineup_needs_four_distinct_drivers():
    with pytest.raises(LineupError):
        Lineup.of(["t1a", "t2a", "t3a"], "t5")
    with pytest.raises(LineupError):
        Lineup.of(["t1a", "t1a", "t2a", "t3a"], "t5")


def test_driver_slots_are_interchangeable():
    """Order must not matter, or a reshuffle would look like four transfers."""
    a = lineup(["t1a", "t2a", "t3a", "t4a"], "t5")
    b = lineup(["t4a", "t3a", "t2a", "t1a"], "t5")
    assert a == b
    assert transfer_cost(a, b) == 0


# -----------------------------------------------------------------------------
# Constraints
# -----------------------------------------------------------------------------


def test_a_valid_lineup_reports_no_problems():
    assert validate_lineup(lineup(["t1a", "t2a", "t3a", "t4a"], "t5"), TEAM_OF_DRIVER) == []
    assert is_valid(lineup(["t1a", "t2a", "t3a", "t4a"], "t5"), TEAM_OF_DRIVER)


def test_two_drivers_from_one_team_are_rejected():
    problems = validate_lineup(
        lineup(["t1a", "t1b", "t2a", "t3a"], "t5"), TEAM_OF_DRIVER
    )
    assert [p.code for p in problems] == [PROBLEM_DUPLICATE_TEAM]


def test_the_team_pick_may_not_duplicate_a_driver_team():
    problems = validate_lineup(
        lineup(["t1a", "t2a", "t3a", "t4a"], "t1"), TEAM_OF_DRIVER
    )
    assert [p.code for p in problems] == [PROBLEM_TEAM_ALREADY_REPRESENTED]


def test_a_driver_with_no_seat_for_the_round_is_rejected():
    problems = validate_lineup(
        lineup(["t1a", "t2a", "t3a", "ghost"], "t5"), TEAM_OF_DRIVER
    )
    assert PROBLEM_UNKNOWN_DRIVER in [p.code for p in problems]


def test_constraints_are_evaluated_against_the_round_not_today():
    """A mid-season transfer changes a driver's team, so the constraint has to
    use the seat they held at that meeting."""
    before = dict(TEAM_OF_DRIVER)
    after = dict(TEAM_OF_DRIVER, t1a="t2")   # t1a moves to team 2 mid-season

    candidate = lineup(["t1a", "t2a", "t3a", "t4a"], "t5")
    assert is_valid(candidate, before) is True
    assert is_valid(candidate, after) is False


# -----------------------------------------------------------------------------
# Transfer cost
# -----------------------------------------------------------------------------


def test_the_first_lineup_of_the_season_is_free():
    assert transfer_cost(None, lineup(["t1a", "t2a", "t3a", "t4a"], "t5")) == 0


def test_an_unchanged_lineup_costs_nothing():
    a = lineup(["t1a", "t2a", "t3a", "t4a"], "t5")
    assert transfer_cost(a, a) == 0


def test_swapping_one_driver_costs_one():
    a = lineup(["t1a", "t2a", "t3a", "t4a"], "t5")
    b = lineup(["t1a", "t2a", "t3a", "t6a"], "t5")
    assert transfer_cost(a, b) == 1


def test_swapping_within_a_team_still_costs_one():
    a = lineup(["t1a", "t2a", "t3a", "t4a"], "t5")
    b = lineup(["t1b", "t2a", "t3a", "t4a"], "t5")
    assert transfer_cost(a, b) == 1


def test_changing_the_team_pick_costs_one():
    a = lineup(["t1a", "t2a", "t3a", "t4a"], "t5")
    b = lineup(["t1a", "t2a", "t3a", "t4a"], "t6")
    assert transfer_cost(a, b) == 1


def test_a_forced_team_relocation_costs_two():
    """The case SPEC.md §2 works through. Drivers from teams 1-4 with team pick
    5; bringing in a driver from team 5 collides with the team pick, so the team
    slot must move too. Two slots change, so it costs two — and is unavailable
    until two transfers are banked."""
    before = lineup(["t1a", "t2a", "t3a", "t4a"], "t5")
    after = lineup(["t5a", "t2a", "t3a", "t4a"], "t1")

    assert is_valid(before, TEAM_OF_DRIVER)
    assert is_valid(after, TEAM_OF_DRIVER)
    assert transfer_cost(before, after) == 2


def test_there_is_no_legal_halfway_house_for_a_forced_relocation():
    """Which is why the editor is a staged draft with an explicit commit: the
    intermediate state cannot be written to the server."""
    intermediate = lineup(["t5a", "t2a", "t3a", "t4a"], "t5")
    assert not is_valid(intermediate, TEAM_OF_DRIVER)


def test_the_forced_move_is_unaffordable_on_one_transfer():
    before = lineup(["t1a", "t2a", "t3a", "t4a"], "t5")
    after = lineup(["t5a", "t2a", "t3a", "t4a"], "t1")
    assert change_is_affordable(before, after, available=1) is False
    assert change_is_affordable(before, after, available=2) is True


def test_a_wholesale_rebuild_costs_five():
    before = lineup(["t1a", "t2a", "t3a", "t4a"], "t5")
    after = lineup(["t6a", "t7a", "t8a", "t9a"], "t10")
    assert transfer_cost(before, after) == 5


# -----------------------------------------------------------------------------
# The bank
# -----------------------------------------------------------------------------


def test_unused_transfers_bank_to_a_maximum_of_two():
    assert transfers_available([]) == 1
    assert transfers_available([0]) == 2
    assert transfers_available([0, 0]) == MAX_BANKED_TRANSFERS
    # A third unused meeting does not accumulate a third.
    assert transfers_available([0, 0, 0]) == MAX_BANKED_TRANSFERS


def test_spending_reduces_the_bank():
    assert transfers_available([0, 1]) == 2
    assert transfers_available([0, 2]) == 1


def test_banking_then_spending_two_is_legal():
    """Two banked transfers buy the forced relocation, which is the whole
    reason the bank exists."""
    assert transfers_available([0]) == 2
    assert transfers_available([0, 2]) == 1


def test_an_impossible_history_raises_rather_than_going_negative():
    with pytest.raises(LineupError):
        transfers_available([2])


# -----------------------------------------------------------------------------
# Enumeration
# -----------------------------------------------------------------------------


def test_the_current_grid_yields_20160_valid_lineups():
    """C(10,4) x 2^4 x 6. A performance expectation, never an invariant."""
    assert count_valid_lineups(GRID) == 20_160
    assert sum(1 for _ in valid_lineups(GRID)) == 20_160


def test_every_enumerated_lineup_is_valid():
    for candidate in valid_lineups(GRID):
        assert not validate_lineup(candidate, TEAM_OF_DRIVER)


def test_enumeration_follows_the_roster_rather_than_assuming_a_grid():
    """Gen4 could bring an eleventh team or a third car. Nothing here cares."""
    eleven_teams = dict(GRID, t11=("t11a", "t11b"))
    assert count_valid_lineups(eleven_teams) > count_valid_lineups(GRID)

    three_cars = dict(GRID, t1=("t1a", "t1b", "t1c"))
    assert count_valid_lineups(three_cars) > count_valid_lineups(GRID)
    assert sum(1 for _ in valid_lineups(three_cars)) == count_valid_lineups(three_cars)


def test_too_few_teams_yields_nothing_rather_than_raising():
    tiny = {f"t{i}": (f"t{i}a", f"t{i}b") for i in range(1, 5)}
    assert count_valid_lineups(tiny) == 0
    assert list(valid_lineups(tiny)) == []


# -----------------------------------------------------------------------------
# Dream team
# -----------------------------------------------------------------------------


def test_the_dream_team_picks_the_highest_scoring_valid_lineup():
    scores = {d: Decimal(0) for d in TEAM_OF_DRIVER}
    for d in ("t1a", "t2a", "t3a", "t4a"):
        scores[d] = Decimal(20)
    team_scores = {t: Decimal(0) for t in GRID}
    team_scores["t5"] = Decimal(9)

    result = dream_team(GRID, scores.__getitem__, team_scores.__getitem__)

    assert result.total == Decimal(89)
    assert result.best.drivers == frozenset({"t1a", "t2a", "t3a", "t4a"})
    assert result.best.team_id == "t5"
    assert result.is_tied is False


def test_the_dream_team_obeys_the_one_driver_per_team_rule():
    """Even when both drivers from one team are the highest scorers."""
    scores = {d: Decimal(0) for d in TEAM_OF_DRIVER}
    scores["t1a"] = Decimal(50)
    scores["t1b"] = Decimal(49)
    team_scores = {t: Decimal(0) for t in GRID}

    result = dream_team(GRID, scores.__getitem__, team_scores.__getitem__)
    picked_teams = {TEAM_OF_DRIVER[d] for d in result.best.drivers}
    assert len(picked_teams) == 4
    assert not {"t1a", "t1b"}.issubset(result.best.drivers)


def test_the_dream_team_never_picks_a_team_it_already_has_a_driver_from():
    scores = {d: Decimal(1) for d in TEAM_OF_DRIVER}
    team_scores = {t: Decimal(0) for t in GRID}
    team_scores["t1"] = Decimal(100)

    result = dream_team(GRID, scores.__getitem__, team_scores.__getitem__)
    assert result.best.team_id == "t1"
    assert TEAM_OF_DRIVER["t1a"] not in {TEAM_OF_DRIVER[d] for d in result.best.drivers}


def test_ties_are_collected_not_broken():
    """A high tie rate signals the scoring gradient is too coarse, which is
    question 7 of the Season 12 simulation. Discarding ties would discard the
    measurement."""
    flat_drivers = {d: Decimal(1) for d in TEAM_OF_DRIVER}
    flat_teams = {t: Decimal(1) for t in GRID}

    result = dream_team(GRID, flat_drivers.__getitem__, flat_teams.__getitem__)
    assert result.is_tied is True
    assert len(result.lineups) == 20_160
    assert result.total == Decimal(5)


def test_ties_can_be_suppressed_for_speed():
    flat_drivers = {d: Decimal(1) for d in TEAM_OF_DRIVER}
    flat_teams = {t: Decimal(1) for t in GRID}
    result = dream_team(
        GRID, flat_drivers.__getitem__, flat_teams.__getitem__, keep_all_ties=False
    )
    assert result.is_tied is False
    assert len(result.lineups) == 1


def test_negative_scores_are_handled():
    """Places lost can take a driver below zero, and the dream team must simply
    avoid them rather than mishandle the sign."""
    scores = {d: Decimal(-4) for d in TEAM_OF_DRIVER}
    for d in ("t1a", "t2a", "t3a", "t4a"):
        scores[d] = Decimal(5)
    team_scores = {t: Decimal(-2) for t in GRID}
    team_scores["t5"] = Decimal(3)

    result = dream_team(GRID, scores.__getitem__, team_scores.__getitem__)
    assert result.best.drivers == frozenset({"t1a", "t2a", "t3a", "t4a"})
    assert result.best.team_id == "t5"
    assert result.total == Decimal(23)


def test_the_dream_team_result_exposes_a_single_best():
    result: DreamTeam = dream_team(
        GRID,
        {d: Decimal(1) for d in TEAM_OF_DRIVER}.__getitem__,
        {t: Decimal(0) for t in GRID}.__getitem__,
    )
    assert result.best in result.lineups
