"""League standings.

The cases that matter are the ones where a plausible implementation is subtly
wrong: an unlocked weekend leaking into the totals, a member with no score
falling out of the table, a tie collapsing into an arbitrary order, and a
hidden member changing the positions everyone else sees.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.leagues import service
from app.leagues.standings import standings


# Anchored on the real clock, not a fixed date. Two of these tests exercise
# the route rather than the function, and the route reads `app.clock.now()`,
# which under test is the real clock and cannot be passed a moment.
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


def _rows(table):
    return {row.username: row for row in table.rows}


# -----------------------------------------------------------------------------
# The basics
# -----------------------------------------------------------------------------


def test_totals_and_positions(
    app, season, league, alice, bob, make_meeting, award
):
    meeting = make_meeting(1, deadline_at=PAST)
    award(alice, meeting, 20)
    award(bob, meeting, 12)

    table = standings(league, season, viewer=alice, now=NOW)
    rows = _rows(table)
    assert rows["alice"].position == 1
    assert rows["alice"].total == Decimal(20)
    assert rows["bob"].position == 2
    assert rows["alice"].is_you


def test_a_member_with_no_score_is_still_in_the_table(
    app, season, league, alice, bob, make_meeting, award
):
    """They are last, not absent. A league table that silently omits people is
    a league table nobody trusts."""
    meeting = make_meeting(1, deadline_at=PAST)
    award(alice, meeting, 20)

    rows = _rows(standings(league, season, viewer=alice, now=NOW))
    assert rows["bob"].total == Decimal(0)
    assert rows["bob"].position == 2


def test_a_tie_shares_a_position(
    app, season, league, alice, bob, make_meeting, award
):
    meeting = make_meeting(1, deadline_at=PAST)
    award(alice, meeting, 15)
    award(bob, meeting, 15)

    rows = _rows(standings(league, season, viewer=alice, now=NOW))
    assert rows["alice"].position == 1
    assert rows["bob"].position == 1
    assert rows["alice"].tied and rows["bob"].tied


def test_an_unlocked_weekend_is_not_counted(
    app, season, league, alice, bob, make_meeting, award
):
    locked = make_meeting(1, deadline_at=PAST)
    unlocked = make_meeting(2, deadline_at=FUTURE)
    award(alice, locked, 10)
    award(alice, unlocked, 90)

    table = standings(league, season, viewer=alice, now=NOW)
    assert [m.id for m in table.meetings] == [locked.id]
    assert _rows(table)["alice"].total == Decimal(10)


def test_a_null_deadline_is_not_counted(
    app, season, league, alice, make_meeting, award
):
    unsynced = make_meeting(1, deadline_at=None)
    award(alice, unsynced, 30)

    table = standings(league, season, viewer=alice, now=NOW)
    assert table.meetings == []
    assert table.is_empty


# -----------------------------------------------------------------------------
# Hiding
# -----------------------------------------------------------------------------


def test_a_hidden_member_leaves_the_table(
    app, season, league, alice, bob, make_meeting, award, db
):
    meeting = make_meeting(1, deadline_at=PAST)
    award(alice, meeting, 5)
    award(bob, meeting, 50)

    membership = service.membership_of(bob, league)
    membership.hidden = True
    db.session.commit()

    table = standings(league, season, viewer=alice, now=NOW)
    assert "bob" not in _rows(table)
    # And with bob gone, alice leads rather than trailing.
    assert _rows(table)["alice"].position == 1


def test_a_hidden_viewer_is_told_rather_than_shown(
    app, season, league, alice, bob, make_meeting, award, db
):
    meeting = make_meeting(1, deadline_at=PAST)
    award(bob, meeting, 5)

    membership = service.membership_of(bob, league)
    membership.hidden = True
    db.session.commit()

    table = standings(league, season, viewer=bob, now=NOW)
    assert table.viewer_hidden
    assert "bob" not in _rows(table)


# -----------------------------------------------------------------------------
# Windows and movement
# -----------------------------------------------------------------------------


def test_the_window_restricts_the_range(
    app, season, league, alice, make_meeting, award
):
    first = make_meeting(1, deadline_at=PAST)
    second = make_meeting(2, deadline_at=RECENT)
    award(alice, first, 100)
    award(alice, second, 7)

    table = standings(league, season, viewer=alice, now=NOW, window=1)
    assert [m.id for m in table.meetings] == [second.id]
    assert _rows(table)["alice"].total == Decimal(7)


def test_movement_compares_against_one_weekend_ago(
    app, season, league, alice, bob, make_meeting, award
):
    """Bob led after weekend one and Alice overtook him in weekend two."""
    first = make_meeting(1, deadline_at=PAST)
    second = make_meeting(2, deadline_at=RECENT)
    award(bob, first, 30)
    award(alice, first, 10)
    award(alice, second, 40)

    rows = _rows(standings(league, season, viewer=alice, now=NOW))
    assert rows["alice"].position == 1
    assert rows["alice"].movement == 1
    assert rows["bob"].movement == -1


def test_movement_is_absent_for_a_single_weekend(
    app, season, league, alice, make_meeting, award
):
    meeting = make_meeting(1, deadline_at=PAST)
    award(alice, meeting, 10)
    assert _rows(standings(league, season, viewer=alice, now=NOW))["alice"].movement is None


def test_last_carries_the_most_recent_weekend(
    app, season, league, alice, make_meeting, award
):
    make_meeting(1, deadline_at=PAST)
    second = make_meeting(2, deadline_at=RECENT)
    award(alice, second, 9)

    rows = _rows(standings(league, season, viewer=alice, now=NOW))
    assert rows["alice"].last == Decimal(9)
    assert rows["alice"].played == 1


# -----------------------------------------------------------------------------
# Provisional
# -----------------------------------------------------------------------------


def test_a_provisional_weekend_is_marked(
    app, season, league, alice, make_meeting, award, db
):
    meeting = make_meeting(1, deadline_at=PAST)
    award(alice, meeting, 8)
    meeting.rounds[0].scoring_provisional = True
    db.session.commit()

    assert standings(league, season, viewer=alice, now=NOW).provisional


# -----------------------------------------------------------------------------
# Membership scope
# -----------------------------------------------------------------------------


def test_a_non_member_is_not_in_the_table(
    app, season, league, alice, make_user, make_meeting, award
):
    """The whole of league scoping: a filter over PickScore, nothing more."""
    outsider = make_user(email="carol@example.com", username="carol")
    meeting = make_meeting(1, deadline_at=PAST)
    award(outsider, meeting, 99)
    award(alice, meeting, 1)

    assert "carol" not in _rows(standings(league, season, viewer=alice, now=NOW))


def test_a_late_joiner_brings_their_whole_season(
    app, season, league, alice, make_user, make_meeting, award
):
    """SPEC.md §2: membership is a view over scores, never a scoring context.
    Joining in March does not cost you December."""
    early = make_meeting(1, deadline_at=PAST)
    late = make_meeting(2, deadline_at=RECENT)
    newcomer = make_user(email="dave@example.com", username="dave")
    award(newcomer, early, 40)
    award(newcomer, late, 40)
    award(alice, early, 10)

    service.join_league(newcomer, league)

    rows = _rows(standings(league, season, viewer=alice, now=NOW))
    assert rows["dave"].total == Decimal(80)
    assert rows["dave"].position == 1


# -----------------------------------------------------------------------------
# The route
# -----------------------------------------------------------------------------


def test_the_detail_page_renders_the_table(
    app, client, signed_in, season, make_meeting, award
):
    user = signed_in(email="alice@example.com", username="alice")
    league = service.create_league(user, "Friends")
    meeting = make_meeting(1, deadline_at=PAST)
    award(user, meeting, 11)

    response = client.get(f"/leagues/{league.id}?last=3")
    assert response.status_code == 200
    assert b"alice" in response.data


def test_a_nonsense_window_falls_back_to_the_season(
    app, client, signed_in, season, make_meeting, award
):
    user = signed_in(email="alice@example.com", username="alice")
    league = service.create_league(user, "Friends")
    make_meeting(1, deadline_at=PAST)

    assert client.get(f"/leagues/{league.id}?last=1000").status_code == 200
    assert client.get(f"/leagues/{league.id}?last=banana").status_code == 200
