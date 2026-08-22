"""Lineup visibility (SPEC.md §2).

The rule is two predicates — the deadline has passed, and the subject is a
co-member who is not hidden — and every test here fails one of them on purpose.
The cases worth having are the ones where the wrong implementation still looks
right: a null deadline, a carried-forward lineup from a sparse snapshot, and a
hidden member who can still see everyone else.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.leagues import service as league_service
from app.leagues import visibility


NOW = datetime(2027, 3, 1, 12, 0, tzinfo=timezone.utc)
PAST = NOW - timedelta(days=7)
FUTURE = NOW + timedelta(days=7)


@pytest.fixture()
def alice(make_user):
    return make_user(email="alice@example.com", username="alice")


@pytest.fixture()
def bob(make_user):
    return make_user(email="bob@example.com", username="bob")


@pytest.fixture()
def carol(make_user):
    return make_user(email="carol@example.com", username="carol")


# -----------------------------------------------------------------------------
# can_view
# -----------------------------------------------------------------------------


def test_co_members_can_view_each_other(alice, bob, make_league):
    make_league(members=[alice, bob])
    assert visibility.can_view(alice, bob)
    assert visibility.can_view(bob, alice)


def test_strangers_cannot_view_each_other(alice, bob, make_league):
    make_league(members=[alice])
    make_league(members=[bob])
    assert not visibility.can_view(alice, bob)


def test_a_user_can_always_view_themselves(alice):
    assert visibility.can_view(alice, alice)


def test_the_global_league_makes_everyone_visible(alice, bob, db):
    league_service.ensure_global_membership(alice)
    league_service.ensure_global_membership(bob)
    assert visibility.can_view(alice, bob)


def test_a_hidden_member_is_not_visible_to_others(alice, bob, make_league, db):
    league = make_league(members=[alice, bob])
    membership = next(m for m in league.memberships if m.user_id == bob.id)
    membership.hidden = True
    db.session.commit()

    assert not visibility.can_view(alice, bob)


def test_a_hidden_member_can_still_view_others(alice, bob, make_league, db):
    """Hiding withdraws your visibility, not your sight."""
    league = make_league(members=[alice, bob])
    membership = next(m for m in league.memberships if m.user_id == bob.id)
    membership.hidden = True
    db.session.commit()

    assert visibility.can_view(bob, alice)
    assert visibility.can_view(bob, bob)


def test_hiding_in_one_league_does_not_hide_in_another(
    alice, bob, make_league, db
):
    hidden_in = make_league(name="Global-ish", members=[alice, bob])
    make_league(name="Friends", members=[alice, bob])
    membership = next(m for m in hidden_in.memberships if m.user_id == bob.id)
    membership.hidden = True
    db.session.commit()

    assert visibility.can_view(alice, bob)


def test_visible_user_returns_none_for_a_stranger(alice, bob, make_league):
    make_league(members=[alice])
    assert visibility.visible_user(alice, bob.id) is None


def test_visible_user_returns_none_for_a_missing_account(alice):
    assert visibility.visible_user(alice, 999999) is None


def test_shared_leagues_names_the_connection(alice, bob, make_league):
    make_league(name="Friends", members=[alice, bob])
    names = [league.name for league in visibility.shared_leagues(alice, bob)]
    assert names == ["Friends"]


# -----------------------------------------------------------------------------
# visible_snapshot
# -----------------------------------------------------------------------------


def test_a_locked_lineup_is_visible_to_a_co_member(
    alice, bob, make_league, make_meeting, make_snapshot, grid
):
    make_league(members=[alice, bob])
    meeting = make_meeting(1, deadline_at=PAST)
    make_snapshot(bob, meeting, grid.lineup())

    seen = visibility.visible_snapshot(alice, bob, meeting, now=NOW)
    assert seen is not None
    assert seen.user_id == bob.id


def test_an_unlocked_lineup_is_hidden_from_a_co_member(
    alice, bob, make_league, make_meeting, make_snapshot, grid
):
    make_league(members=[alice, bob])
    meeting = make_meeting(1, deadline_at=FUTURE)
    make_snapshot(bob, meeting, grid.lineup())

    assert visibility.visible_snapshot(alice, bob, meeting, now=NOW) is None


def test_a_null_deadline_is_not_locked(
    alice, bob, make_league, make_meeting, make_snapshot, grid
):
    """The trap. An unsynced meeting has no deadline, and no deadline means
    the weekend has not locked — the same reading `grace_meeting` takes."""
    make_league(members=[alice, bob])
    meeting = make_meeting(1, deadline_at=None)
    make_snapshot(bob, meeting, grid.lineup())

    assert visibility.visible_snapshot(alice, bob, meeting, now=NOW) is None


def test_a_locked_lineup_is_hidden_from_a_stranger(
    alice, bob, make_league, make_meeting, make_snapshot, grid
):
    make_league(members=[alice])
    meeting = make_meeting(1, deadline_at=PAST)
    make_snapshot(bob, meeting, grid.lineup())

    assert visibility.visible_snapshot(alice, bob, meeting, now=NOW) is None


def test_a_locked_lineup_is_hidden_from_a_hidden_members_watchers(
    alice, bob, make_league, make_meeting, make_snapshot, grid, db
):
    league = make_league(members=[alice, bob])
    membership = next(m for m in league.memberships if m.user_id == bob.id)
    membership.hidden = True
    db.session.commit()

    meeting = make_meeting(1, deadline_at=PAST)
    make_snapshot(bob, meeting, grid.lineup())

    assert visibility.visible_snapshot(alice, bob, meeting, now=NOW) is None


def test_a_sparse_snapshot_carries_forward(
    alice, bob, make_league, make_meeting, make_snapshot, grid
):
    """Bob picked at meeting 1 and never again. His meeting 3 lineup is
    meeting 1's, and a co-member sees it there."""
    make_league(members=[alice, bob])
    first = make_meeting(1, deadline_at=PAST)
    make_meeting(2, deadline_at=PAST)
    third = make_meeting(3, deadline_at=PAST)
    make_snapshot(bob, first, grid.lineup())

    seen = visibility.visible_snapshot(alice, bob, third, now=NOW)
    assert seen is not None
    assert seen.meeting_id == first.id


def test_no_snapshot_at_or_before_reads_as_nothing(
    alice, bob, make_league, make_meeting, make_snapshot, grid
):
    make_league(members=[alice, bob])
    first = make_meeting(1, deadline_at=PAST)
    second = make_meeting(2, deadline_at=PAST)
    make_snapshot(bob, second, grid.lineup())

    assert visibility.visible_snapshot(alice, bob, first, now=NOW) is None


# -----------------------------------------------------------------------------
# visible_season_lineups
# -----------------------------------------------------------------------------


def test_a_season_shows_only_locked_meetings(
    alice, bob, season, make_league, make_meeting, make_snapshot, grid
):
    make_league(members=[alice, bob])
    first = make_meeting(1, deadline_at=PAST)
    second = make_meeting(2, deadline_at=PAST)
    make_meeting(3, deadline_at=FUTURE)
    make_snapshot(bob, first, grid.lineup())

    rows = visibility.visible_season_lineups(alice, bob, season, now=NOW)
    assert [m.id for m, _ in rows] == [first.id, second.id]
    # Carried forward into meeting 2, which is the whole point of sparseness.
    assert all(snapshot is not None for _, snapshot in rows)


def test_an_unlocked_snapshot_never_reaches_the_season_list(
    alice, bob, season, make_league, make_meeting, make_snapshot, grid
):
    make_league(members=[alice, bob])
    locked = make_meeting(1, deadline_at=PAST)
    unlocked = make_meeting(2, deadline_at=FUTURE)
    make_snapshot(bob, unlocked, grid.lineup(driver_teams=(5, 6, 7, 8), team=9))

    rows = visibility.visible_season_lineups(alice, bob, season, now=NOW)
    assert [m.id for m, _ in rows] == [locked.id]
    assert rows[0][1] is None


def test_a_season_is_empty_for_a_stranger(
    alice, bob, season, make_league, make_meeting, make_snapshot, grid
):
    make_league(members=[alice])
    meeting = make_meeting(1, deadline_at=PAST)
    make_snapshot(bob, meeting, grid.lineup())

    assert visibility.visible_season_lineups(alice, bob, season, now=NOW) == []


# -----------------------------------------------------------------------------
# visible_snapshots_at
# -----------------------------------------------------------------------------


def test_a_weekend_shows_every_visible_member(
    alice, bob, carol, make_league, make_meeting, make_snapshot, grid
):
    make_league(members=[alice, bob])
    meeting = make_meeting(1, deadline_at=PAST)
    make_snapshot(alice, meeting, grid.lineup())
    make_snapshot(bob, meeting, grid.lineup(driver_teams=(1, 2, 3, 4), team=5))
    make_snapshot(carol, meeting, grid.lineup(driver_teams=(5, 6, 7, 8), team=9))

    seen = visibility.visible_snapshots_at(alice, meeting, now=NOW)
    assert {s.user_id for s in seen} == {alice.id, bob.id}


def test_a_weekend_shows_nothing_before_the_deadline(
    alice, bob, make_league, make_meeting, make_snapshot, grid
):
    make_league(members=[alice, bob])
    meeting = make_meeting(1, deadline_at=FUTURE)
    make_snapshot(bob, meeting, grid.lineup())

    assert visibility.visible_snapshots_at(alice, meeting, now=NOW) == []


def test_a_hidden_member_still_sees_their_own_row(
    alice, bob, make_league, make_meeting, make_snapshot, grid, db
):
    league = make_league(members=[alice, bob])
    membership = next(m for m in league.memberships if m.user_id == bob.id)
    membership.hidden = True
    db.session.commit()

    meeting = make_meeting(1, deadline_at=PAST)
    make_snapshot(alice, meeting, grid.lineup())
    make_snapshot(bob, meeting, grid.lineup(driver_teams=(1, 2, 3, 4), team=5))

    seen = visibility.visible_snapshots_at(bob, meeting, now=NOW)
    assert {s.user_id for s in seen} == {alice.id, bob.id}


# -----------------------------------------------------------------------------
# The global league itself
# -----------------------------------------------------------------------------


def test_ensure_global_league_is_idempotent(db):
    first = league_service.ensure_global_league()
    second = league_service.ensure_global_league()
    assert first.id == second.id


def test_ensure_global_membership_preserves_hiding(alice, db):
    membership = league_service.ensure_global_membership(alice)
    membership.hidden = True
    db.session.commit()

    again = league_service.ensure_global_membership(alice)
    assert again.id == membership.id
    assert again.hidden is True
