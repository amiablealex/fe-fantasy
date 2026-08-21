"""The game rules as a player experiences them.

`tests/test_lineup_models.py` asserts what the database refuses to store. This
asserts what the service refuses to write, which is a different and larger set:
the deadline, the open weekend, the grace period and the transfer bank are all
rules with no schema behind them.

Times are passed in explicitly rather than patched, because every function here
takes `now`. A test that has to freeze the clock is a test telling you the code
reads a global when it should take an argument.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.lineups import service
from app.models.lineup import LineupSnapshot
from app.scoring import lineups as rules

NOW = datetime(2027, 3, 1, 12, 0, tzinfo=timezone.utc)


def _past(days: int) -> datetime:
    return NOW - timedelta(days=days)


def _future(days: int) -> datetime:
    return NOW + timedelta(days=days)


@pytest.fixture()
def calendar(make_meeting):
    """Four weekends: two run, two to come.

    Meeting 3 is the open one throughout, which makes it the subject of almost
    every test here.
    """
    return [
        make_meeting(1, deadline_at=_past(60)),
        make_meeting(2, deadline_at=_past(30)),
        make_meeting(3, deadline_at=_future(7)),
        make_meeting(4, deadline_at=_future(37), rounds=2),
    ]


@pytest.fixture()
def early_user(db, make_user):
    """Registered before the season. Grace covers meeting 1 only."""
    user = make_user(email="early@example.com", username="early")
    user.created_at = _past(120)
    db.session.commit()
    return user


def _commit(user, meeting, lineup):
    return service.commit(user, meeting, lineup, now=NOW)


def _seed(db, user, meeting, lineup, cost=0):
    """Write a snapshot directly, bypassing the rules.

    Used to set up a history the service then has to read. Going through
    `commit` would mean every test about the bank was also a test about the
    deadline.
    """
    record = LineupSnapshot.build(
        user_id=user.id,
        season_id=meeting.season_id,
        meeting_id=meeting.id,
        lineup=lineup,
        transfer_cost=cost,
    )
    db.session.add(record)
    db.session.commit()
    return record


# -----------------------------------------------------------------------------
# The open weekend
# -----------------------------------------------------------------------------


def test_open_meeting_is_the_earliest_unlocked(season, calendar):
    assert service.open_meeting(season, NOW).sequence == 3


def test_a_locked_weekend_refuses_a_commit(early_user, grid, calendar):
    with pytest.raises(service.CommitRefused):
        _commit(early_user, calendar[1], grid.lineup())


def test_a_future_weekend_refuses_a_commit(early_user, grid, calendar):
    """Meeting 4 is unlocked, but meeting 3 is still open.

    Editing ahead would make meeting 4's cost depend on a meeting 3 lineup that
    is still moving, so there is no honest figure to show.
    """
    with pytest.raises(service.CommitRefused):
        _commit(early_user, calendar[3], grid.lineup())


# -----------------------------------------------------------------------------
# Grace
# -----------------------------------------------------------------------------


def test_grace_covers_the_first_weekend_only(early_user, season, calendar):
    assert service.grace_meeting(early_user, season).sequence == 1
    assert service.is_in_grace(early_user, calendar[0])
    assert not service.is_in_grace(early_user, calendar[1])


def test_grace_for_a_late_joiner_runs_to_their_own_first_deadline(
    db, make_user, season, calendar
):
    """Registered after meeting 2 ran, so meeting 3 is their free weekend."""
    user = make_user(email="late@example.com", username="late")
    user.created_at = _past(10)
    db.session.commit()

    assert service.grace_meeting(user, season).sequence == 3
    assert service.is_in_grace(user, calendar[2])


def test_grace_allows_a_change_no_bank_could_pay_for(
    db, make_user, season, grid, calendar
):
    user = make_user(email="late@example.com", username="late")
    user.created_at = _past(10)
    db.session.commit()

    _commit(user, calendar[2], grid.lineup(driver_teams=(0, 1, 2, 3), team=4))
    record = _commit(user, calendar[2], grid.lineup(driver_teams=(5, 6, 7, 8), team=9))

    # Every slot changed and it was allowed. The stored cost is nonetheless 0,
    # because a grace weekend is by construction the player's first: there is no
    # earlier snapshot to diff against, so the free period needs no exemption in
    # the arithmetic.
    assert service.transfer_budget(user, calendar[2]).unlimited
    assert record.transfer_cost == 0


# -----------------------------------------------------------------------------
# The bank
# -----------------------------------------------------------------------------


def test_first_charged_weekend_has_one_transfer(early_user, calendar):
    assert service.transfer_budget(early_user, calendar[1]) == service.TransferBudget(1)


def test_an_unused_transfer_banks(early_user, calendar):
    """Nothing spent at meeting 2, so meeting 3 opens holding two."""
    assert service.transfer_budget(early_user, calendar[2]).available == 2


def test_the_bank_caps_at_two(early_user, calendar):
    """Meetings 2 and 3 both untouched leaves two at meeting 4, never three."""
    budget = service.transfer_budget(early_user, calendar[3])
    assert budget.available == rules.MAX_BANKED_TRANSFERS


def test_spending_reduces_the_bank(db, early_user, grid, calendar):
    _seed(db, early_user, calendar[1], grid.lineup(driver_teams=(0, 1, 2, 5)), cost=1)
    assert service.transfer_budget(early_user, calendar[2]).available == 1


# -----------------------------------------------------------------------------
# Commit
# -----------------------------------------------------------------------------


def test_an_invalid_lineup_is_refused(early_user, grid, calendar):
    """Two drivers from one team, which the editor should never have offered."""
    both_cars = rules.Lineup.of(
        [
            grid.driver_at(0, 0).id,
            grid.driver_at(0, 1).id,
            grid.driver_at(1).id,
            grid.driver_at(2).id,
        ],
        grid.teams[4].id,
    )
    with pytest.raises(service.CommitRefused) as refusal:
        _commit(early_user, calendar[2], both_cars)
    assert refusal.value.problems


def test_the_first_lineup_of_a_season_is_free(db, early_user, grid, calendar):
    record = _commit(early_user, calendar[2], grid.lineup())
    assert record.transfer_cost == 0


def test_re_editing_before_the_deadline_does_not_accumulate_cost(
    db, early_user, grid, calendar
):
    """Changing your mind is free however many times you do it.

    The cost baseline is the last snapshot from an *earlier* meeting, never the
    row being rewritten — otherwise the bank would depend on how often someone
    opened the app.
    """
    _seed(db, early_user, calendar[1], grid.lineup(driver_teams=(0, 1, 2, 3)))

    first = _commit(early_user, calendar[2], grid.lineup(driver_teams=(0, 1, 2, 5)))
    assert first.transfer_cost == 1

    again = _commit(early_user, calendar[2], grid.lineup(driver_teams=(0, 1, 2, 6)))
    assert again.transfer_cost == 1
    assert again.id == first.id

    unchanged = _commit(early_user, calendar[2], grid.lineup(driver_teams=(0, 1, 2, 3)))
    assert unchanged.transfer_cost == 0


def test_a_change_beyond_the_bank_is_refused(db, early_user, grid, calendar):
    _seed(db, early_user, calendar[1], grid.lineup(driver_teams=(0, 1, 2, 3)), cost=1)
    assert service.transfer_budget(early_user, calendar[2]).available == 1

    with pytest.raises(service.CommitRefused):
        _commit(early_user, calendar[2], grid.lineup(driver_teams=(0, 1, 5, 6)))


def test_forced_relocation_costs_two_and_needs_two_banked(
    db, early_user, grid, calendar
):
    """SPEC.md §2's worked example, end to end.

    Drivers from teams 0-3, team pick 4. Bringing in team 4's driver collides
    with the team slot, so the team slot must move too: two slots, spent
    atomically, unavailable at one transfer.
    """
    committed = _seed(
        db, early_user, calendar[1],
        grid.lineup(driver_teams=(0, 1, 2, 3), team=4), cost=1,
    )
    relocated = grid.lineup(driver_teams=(0, 1, 2, 4), team=5)

    assert service.transfer_budget(early_user, calendar[2]).available == 1
    with pytest.raises(service.CommitRefused):
        _commit(early_user, calendar[2], relocated)

    # Bank meeting 2's transfer instead of spending it, and the move opens up.
    committed.transfer_cost = 0
    db.session.commit()
    assert service.transfer_budget(early_user, calendar[2]).available == 2

    record = _commit(early_user, calendar[2], relocated)
    assert record.transfer_cost == 2


# -----------------------------------------------------------------------------
# Reading a lineup back
# -----------------------------------------------------------------------------


def test_an_untouched_lineup_carries_forward(db, early_user, grid, calendar):
    """Sparse storage: no row at meeting 3, but the player still has a lineup.

    This is the graceful degradation the whole game design rests on — a
    forgotten month still scores.
    """
    lineup = grid.lineup()
    _seed(db, early_user, calendar[0], lineup)

    assert service.snapshot_for(early_user, calendar[2]) is None
    assert service.effective_snapshot(early_user, calendar[2]).to_lineup() == lineup


def test_state_separates_the_baseline_from_the_draft(db, early_user, grid, calendar):
    carried = grid.lineup(driver_teams=(0, 1, 2, 3))
    edited = grid.lineup(driver_teams=(0, 1, 2, 5))
    _seed(db, early_user, calendar[1], carried)
    _seed(db, early_user, calendar[2], edited, cost=1)

    state = service.lineup_state(early_user, calendar[2], now=NOW)
    assert state.editable and not state.locked
    assert state.starting_draft == edited
    assert state.baseline == carried
    assert not state.is_first_lineup


def test_state_for_a_player_who_has_never_picked(early_user, grid, calendar):
    state = service.lineup_state(early_user, calendar[2], now=NOW)
    assert state.is_first_lineup
    assert state.starting_draft is None
    assert state.baseline is None
    assert len(state.roster.drivers_by_team) == 10
