"""The front page: what a player sees on opening the app.

There is no email in this game, so everything that would otherwise be a
reminder has to be legible here. These tests are mostly about that — the
deadline, the bank, and the unchanged-lineup condition — plus the one rule that
decides which weekend the page is about.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.lineups import service
from app.lineups.routes import countdown


def _past(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _future(days: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


@pytest.fixture()
def calendar(make_meeting):
    return [
        make_meeting(1, deadline_at=_past(30)),
        make_meeting(2, deadline_at=_future(7.5)),
        make_meeting(3, deadline_at=_future(37)),
    ]


@pytest.fixture()
def player(db, signed_in):
    user = signed_in(email="player@example.com", username="player")
    user.created_at = _past(90)
    db.session.commit()
    return user


def _seed(db, user, meeting, lineup, cost=0):
    from app.models.lineup import LineupSnapshot

    record = LineupSnapshot.build(
        user_id=user.id, season_id=meeting.season_id, meeting_id=meeting.id,
        lineup=lineup, transfer_cost=cost,
    )
    db.session.add(record)
    db.session.commit()
    return record


# -----------------------------------------------------------------------------
# The countdown
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hours,expected",
    [
        (-1, "Locked"),
        (0.5, "30 min"),
        (5, "5 hours"),
        (49, "2 days"),
        (504, "21 days"),
    ],
)
def test_countdown_picks_an_honest_unit(hours, expected):
    """A player three weeks out should not read 504 hours, and a player twenty
    minutes out must not read "today"."""
    moment = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert countdown(moment + timedelta(hours=hours), moment) == expected


def test_countdown_without_a_deadline():
    moment = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert countdown(None, moment) == "TBC"


# -----------------------------------------------------------------------------
# The page
# -----------------------------------------------------------------------------


def test_signed_out_gets_a_landing_not_a_redirect(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Sign in" in response.data


def test_home_shows_the_live_weekend_not_the_editable_one(
    db, client, player, season, grid, calendar
):
    """Meeting 1 has run and meeting 2 is open.

    The front page is about meeting 1, because that is the weekend whose picks
    are locked in. Meeting 2 is a link.
    """
    _seed(db, player, calendar[0], grid.lineup())
    response = client.get("/")
    assert b"City 1" in response.data
    assert b"locked" in response.data
    assert b"Driver01" in response.data


def test_home_names_the_next_deadline(client, player, season, grid, calendar):
    response = client.get("/")
    assert b"City 2" in response.data
    assert b"7 days" in response.data


def test_the_unchanged_nudge_appears_when_nothing_is_committed(
    db, client, player, season, grid, calendar
):
    _seed(db, player, calendar[0], grid.lineup())
    response = client.get("/")
    assert b"unchanged since" in response.data


def test_the_nudge_goes_away_once_the_open_weekend_is_committed(
    db, client, player, season, grid, calendar
):
    _seed(db, player, calendar[0], grid.lineup())
    _seed(db, player, calendar[1], grid.lineup(driver_teams=(0, 1, 2, 5)), cost=1)
    response = client.get("/")
    assert b"unchanged since" not in response.data


def test_the_bank_is_on_the_front_page(db, client, player, season, grid, calendar):
    """Meeting 1 is the grace weekend, so meeting 2 opens holding one."""
    _seed(db, player, calendar[0], grid.lineup())
    assert service.transfer_budget(player, calendar[1]).available == 1
    response = client.get("/")
    assert b"Transfers available" in response.data


def test_grace_says_free_rather_than_a_number(
    db, client, make_user, signed_in, season, grid, make_meeting
):
    """A player whose first deadline has not passed has no budget to show."""
    make_meeting(1, deadline_at=_future(7))
    user = signed_in(email="new@example.com", username="new")
    user.created_at = _past(1)
    db.session.commit()

    response = client.get("/")
    assert b"Free changes until the first deadline" in response.data
    assert b"Transfers available" not in response.data


def test_a_player_with_no_lineup_is_told_so(client, player, season, grid, calendar):
    response = client.get("/")
    assert b"You had no lineup in for this weekend" in response.data
    assert b"Pick your lineup" in response.data
