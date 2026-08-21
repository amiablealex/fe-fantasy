"""Storage-level guarantees for the game schema.

These test the database, not the rules. The rules are `app/scoring/lineups.py`
and are tested without a database at all; what is asserted here is that a
lineup which breaks one of them cannot be *stored*, because the editor is not
the only thing that will ever write to these tables.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.lineup import PICK_DRIVER, PICK_TEAM, LineupPick, LineupSnapshot
from app.scoring import lineups as rules


def _snapshot(db, user, season, meeting, lineup, cost=0) -> LineupSnapshot:
    record = LineupSnapshot.build(
        user_id=user.id,
        season_id=season.id,
        meeting_id=meeting.id,
        lineup=lineup,
        transfer_cost=cost,
    )
    db.session.add(record)
    db.session.commit()
    return record


def test_snapshot_round_trips(db, make_user, season, grid, make_meeting):
    user = make_user()
    meeting = make_meeting(1)
    lineup = grid.lineup()

    record = _snapshot(db, user, season, meeting, lineup)
    db.session.expire_all()

    stored = db.session.get(LineupSnapshot, record.id)
    assert len(stored.picks) == rules.TOTAL_SLOTS
    assert stored.is_complete
    assert stored.to_lineup() == lineup


def test_driver_order_is_not_identity(db, make_user, season, grid, make_meeting):
    """The four slots are interchangeable, so a reordering is not a transfer.

    The regression this guards is real: five columns on the snapshot would make
    the same four drivers in a different order look like four changed slots.
    """
    user = make_user()
    lineup = grid.lineup(driver_teams=(0, 1, 2, 3))
    shuffled = grid.lineup(driver_teams=(3, 2, 1, 0))

    first = _snapshot(db, user, season, make_meeting(1), lineup)
    second = _snapshot(db, user, season, make_meeting(2), shuffled)

    assert first.to_lineup() == second.to_lineup()
    assert rules.transfer_cost(first.to_lineup(), second.to_lineup()) == 0


def test_one_snapshot_per_user_per_meeting(db, make_user, season, grid, make_meeting):
    user = make_user()
    meeting = make_meeting(1)
    _snapshot(db, user, season, meeting, grid.lineup())

    with pytest.raises(IntegrityError):
        _snapshot(db, user, season, meeting, grid.lineup(driver_teams=(5, 6, 7, 8), team=9))
    db.session.rollback()


def test_same_driver_twice_is_rejected(db, make_user, season, grid, make_meeting):
    user = make_user()
    record = _snapshot(db, user, season, make_meeting(1), grid.lineup())

    record.picks.append(LineupPick.for_driver(grid.driver_at(0).id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_two_team_picks_are_rejected(db, make_user, season, grid, make_meeting):
    """The partial unique index, which Alembic is capable of omitting silently."""
    user = make_user()
    record = _snapshot(db, user, season, make_meeting(1), grid.lineup())

    record.picks.append(LineupPick.for_team(grid.teams[5].id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_a_pick_cannot_be_both_kinds(db, make_user, season, grid, make_meeting):
    user = make_user()
    record = _snapshot(db, user, season, make_meeting(1), grid.lineup())

    record.picks.append(LineupPick(
        kind=PICK_DRIVER,
        driver_id=grid.driver_at(9).id,
        team_id=grid.teams[9].id,
    ))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_deleting_a_user_removes_their_lineups(db, make_user, season, grid, make_meeting):
    user = make_user()
    record = _snapshot(db, user, season, make_meeting(1), grid.lineup())
    snapshot_id = record.id

    db.session.delete(user)
    db.session.commit()

    assert db.session.get(LineupSnapshot, snapshot_id) is None
    remaining = db.session.scalars(
        select(LineupPick).where(LineupPick.snapshot_id == snapshot_id)
    ).all()
    assert remaining == []


def test_deleting_a_picked_driver_is_refused(db, make_user, season, grid, make_meeting):
    """RESTRICT, not CASCADE.

    Drivers are global and keyed on a provider UUID, so deleting one is a
    mistake rather than a routine operation — and it must not quietly shred
    every stored lineup that picked them.
    """
    user = make_user()
    _snapshot(db, user, season, make_meeting(1), grid.lineup())

    db.session.delete(grid.driver_at(0))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_relationships_resolve(db, make_user, season, grid, make_meeting):
    """`pick.driver` is a Driver, not a bound method.

    Direct regression on the `for_driver` rename: a classmethod sharing a name
    with a relationship shadows it, and nothing about that failure is loud.
    """
    user = make_user()
    record = _snapshot(db, user, season, make_meeting(1), grid.lineup())

    driver_picks = [p for p in record.picks if p.kind == PICK_DRIVER]
    team_pick = next(p for p in record.picks if p.kind == PICK_TEAM)

    assert {p.driver.number for p in driver_picks} == {1, 3, 5, 7}
    assert team_pick.team.name == "Team E"
