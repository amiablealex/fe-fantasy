"""Friend profiles.

The profile is the first screen in the app that renders another person's data,
so most of what is worth testing is what it refuses to render.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.leagues import service
from app.leagues.profile import player_profile, weekend_detail


NOW = datetime.now(timezone.utc)
PAST = NOW - timedelta(days=30)
RECENT = NOW - timedelta(days=2)
FUTURE = NOW + timedelta(days=7)


@pytest.fixture()
def alice(make_user):
    return make_user(email="alice@example.com", username="alice")


@pytest.fixture()
def bob(make_user):
    return make_user(email="bob@example.com", username="bob")


@pytest.fixture()
def league(alice, bob):
    league = service.create_league(alice, "Friends")
    service.join_league(bob, league)
    return league


# -----------------------------------------------------------------------------
# The season summary
# -----------------------------------------------------------------------------


def test_a_profile_lists_locked_weekends_newest_first(
    app, season, league, alice, bob, make_meeting, award
):
    first = make_meeting(1, deadline_at=PAST)
    second = make_meeting(2, deadline_at=RECENT)
    make_meeting(3, deadline_at=FUTURE)
    award(bob, first, 10)
    award(bob, second, 25)

    profile = player_profile(alice, bob, season, now=NOW)
    assert [row.meeting.id for row in profile.weekends] == [second.id, first.id]
    assert profile.total == Decimal(35)
    assert profile.played == 2


def test_an_unlocked_weekend_is_absent_not_blank(
    app, season, league, alice, bob, make_meeting, award
):
    """A blank row for the open weekend invites the reader to wonder whether
    they have picked yet, which is exactly what §2 hides."""
    locked = make_meeting(1, deadline_at=PAST)
    unlocked = make_meeting(2, deadline_at=FUTURE)
    award(bob, locked, 10)
    award(bob, unlocked, 99)

    profile = player_profile(alice, bob, season, now=NOW)
    assert [row.meeting.id for row in profile.weekends] == [locked.id]
    assert profile.total == Decimal(10)


def test_a_carried_lineup_is_marked_as_not_committed(
    app, season, league, alice, bob, make_meeting, make_snapshot, grid
):
    first = make_meeting(1, deadline_at=PAST)
    make_meeting(2, deadline_at=RECENT)
    make_snapshot(bob, first, grid.lineup(), transfer_cost=2)

    profile = player_profile(alice, bob, season, now=NOW)
    carried = profile.row_for(2)
    committed = profile.row_for(1)

    assert carried.snapshot.meeting_id == first.id
    assert not carried.committed
    assert carried.transfer_cost is None
    assert committed.committed
    assert committed.transfer_cost == 2


def test_a_stranger_sees_nothing(
    app, season, alice, bob, make_meeting, award
):
    meeting = make_meeting(1, deadline_at=PAST)
    award(bob, meeting, 10)

    profile = player_profile(alice, bob, season, now=NOW)
    assert profile.weekends == []
    assert profile.total == Decimal(0)


def test_your_own_profile_works(
    app, season, alice, make_meeting, award
):
    meeting = make_meeting(1, deadline_at=PAST)
    award(alice, meeting, 14)

    profile = player_profile(alice, alice, season, now=NOW)
    assert profile.is_you
    assert profile.total == Decimal(14)


# -----------------------------------------------------------------------------
# One weekend
# -----------------------------------------------------------------------------


def test_a_weekend_detail_renders_five_picks(
    app, season, league, alice, bob, make_meeting, award
):
    meeting = make_meeting(1, deadline_at=PAST)
    award(bob, meeting, 12)

    detail = weekend_detail(alice, bob, season, meeting, now=NOW)
    assert detail is not None
    assert len(detail.picks) == 5


def test_an_unlocked_weekend_has_no_detail(
    app, season, league, alice, bob, make_meeting, award
):
    meeting = make_meeting(1, deadline_at=FUTURE)
    award(bob, meeting, 12)

    assert weekend_detail(alice, bob, season, meeting, now=NOW) is None


def test_a_stranger_gets_no_detail(
    app, season, alice, bob, make_meeting, award
):
    meeting = make_meeting(1, deadline_at=PAST)
    award(bob, meeting, 12)

    assert weekend_detail(alice, bob, season, meeting, now=NOW) is None


# -----------------------------------------------------------------------------
# The route
# -----------------------------------------------------------------------------


def test_the_route_renders_for_a_co_member(
    app, client, signed_in, season, make_user, make_meeting, award
):
    viewer = signed_in(email="alice@example.com", username="alice")
    other = make_user(email="bob@example.com", username="bob")
    league = service.create_league(viewer, "Friends")
    service.join_league(other, league)

    meeting = make_meeting(1, deadline_at=PAST)
    award(other, meeting, 12)

    response = client.get(f"/players/{other.id}")
    assert response.status_code == 200
    assert b"bob" in response.data


def test_the_route_is_404_for_a_stranger(
    app, client, signed_in, season, make_user
):
    signed_in(email="alice@example.com", username="alice")
    other = make_user(email="bob@example.com", username="bob")
    assert client.get(f"/players/{other.id}").status_code == 404


def test_the_route_is_404_for_a_missing_account(app, client, signed_in):
    signed_in(email="alice@example.com", username="alice")
    assert client.get("/players/999999").status_code == 404


def test_an_out_of_range_weekend_falls_back(
    app, client, signed_in, season, make_meeting, award
):
    """The visible list is the gate, so an unlocked weekend cannot be reached
    by editing the query string."""
    viewer = signed_in(email="alice@example.com", username="alice")
    make_meeting(1, deadline_at=PAST)
    make_meeting(2, deadline_at=FUTURE)
    award(viewer, make_meeting(3, deadline_at=RECENT), 5)

    assert client.get(f"/players/{viewer.id}?m=2").status_code == 200
    assert client.get(f"/players/{viewer.id}?m=99").status_code == 200
    assert client.get(f"/players/{viewer.id}?m=banana").status_code == 200
