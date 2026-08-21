"""The editor as a browser meets it.

`test_lineup_service.py` covers the rules. This covers the wiring: that the
draft in the query string reaches the rules, that a commit reaches the
database, and that a refusal reaches the reader rather than a traceback.

Deadlines here are relative to the real clock, because the routes read it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.lineups import service
from app.models.lineup import LineupSnapshot


def _past(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _future(days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


@pytest.fixture()
def calendar(make_meeting):
    """Meeting 2 is open; meeting 1 has run."""
    return [
        make_meeting(1, deadline_at=_past(30)),
        make_meeting(2, deadline_at=_future(7)),
        make_meeting(3, deadline_at=_future(37)),
    ]


@pytest.fixture()
def player(db, signed_in):
    user = signed_in(email="player@example.com", username="player")
    user.created_at = _past(90)
    db.session.commit()
    return user


def _post(client, drivers, team):
    return client.post(
        "/lineup",
        data={"d": ",".join(str(d) for d in drivers), "t": str(team)},
        follow_redirects=True,
    )


def test_editor_requires_signing_in(client, season, grid, calendar):
    response = client.get("/lineup")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_editor_opens_on_the_open_weekend(client, player, season, grid, calendar):
    response = client.get("/lineup")
    assert response.status_code == 200
    assert b"City 2" in response.data


def test_a_draft_in_the_url_fills_the_slots(client, player, season, grid, calendar):
    picks = [grid.driver_at(t).id for t in range(4)]
    response = client.get(
        f"/lineup?d={','.join(str(p) for p in picks)}&t={grid.teams[4].id}"
    )
    assert response.status_code == 200
    assert b"Driver01" in response.data
    assert b"Team E" in response.data


def test_a_broken_draft_states_the_problem(client, player, season, grid, calendar):
    """Both of one team's cars. The picker allows reaching this state on
    purpose — a forced relocation has no legal intermediate — so the editor has
    to explain it rather than pretend it cannot happen."""
    picks = [
        grid.driver_at(0, 0).id,
        grid.driver_at(0, 1).id,
        grid.driver_at(1).id,
        grid.driver_at(2).id,
    ]
    response = client.get(
        f"/lineup?d={','.join(str(p) for p in picks)}&t={grid.teams[4].id}"
    )
    assert b"Too many drivers" in response.data


def test_committing_stores_a_snapshot(db, client, player, season, grid, calendar):
    picks = [grid.driver_at(t).id for t in range(4)]
    response = _post(client, picks, grid.teams[4].id)
    assert response.status_code == 200

    stored = db.session.query(LineupSnapshot).one()
    assert stored.meeting_id == calendar[1].id
    assert stored.driver_ids == sorted(picks)
    assert stored.team_id == grid.teams[4].id
    assert stored.transfer_cost == 0


def test_a_stored_lineup_reopens_in_the_editor(
    db, client, player, season, grid, calendar
):
    picks = [grid.driver_at(t).id for t in range(4)]
    _post(client, picks, grid.teams[4].id)

    response = client.get("/lineup")
    assert b"Driver01" in response.data
    assert b"No changes to commit" in response.data


def test_an_invalid_commit_is_refused_with_a_message(
    db, client, player, season, grid, calendar
):
    picks = [
        grid.driver_at(0, 0).id,
        grid.driver_at(0, 1).id,
        grid.driver_at(1).id,
        grid.driver_at(2).id,
    ]
    response = _post(client, picks, grid.teams[4].id)
    assert b"Only one driver per team" in response.data
    assert db.session.query(LineupSnapshot).count() == 0


def test_an_incomplete_commit_is_refused(db, client, player, season, grid, calendar):
    response = _post(client, [grid.driver_at(0).id], grid.teams[4].id)
    assert b"Pick four drivers" in response.data
    assert db.session.query(LineupSnapshot).count() == 0


def test_the_editor_survives_a_season_with_no_open_weekend(
    client, player, season, grid, make_meeting
):
    make_meeting(1, deadline_at=_past(30))
    response = client.get("/lineup")
    assert response.status_code == 200
    assert b"Nothing to pick for" in response.data


def test_commit_goes_through_the_service(db, client, player, season, grid, calendar):
    """The route is a wrapper; the rules are the service's.

    Asserted by the shape of what lands: a cost derived from the previous
    snapshot rather than from the form.
    """
    first = [grid.driver_at(t).id for t in range(4)]
    _post(client, first, grid.teams[4].id)

    # Move the snapshot back a meeting so the next commit has a baseline.
    stored = db.session.query(LineupSnapshot).one()
    stored.meeting_id = calendar[0].id
    db.session.commit()

    swapped = [grid.driver_at(t).id for t in (0, 1, 2, 5)]
    _post(client, swapped, grid.teams[4].id)

    latest = service.snapshot_for(player, calendar[1])
    assert latest.transfer_cost == 1
