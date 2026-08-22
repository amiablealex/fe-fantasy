"""The lineup editor's commit affordance.

Phase 4 gated it on `diff.has_changes`, which is measured against the *cost
baseline* — the last snapshot from an earlier meeting. A player editing their
first-ever lineup has no earlier snapshot, so the diff was empty however much
they changed and the button never enabled.

These assert on structural classes rather than on wording, per SPEC.md §11: the
claim is that the affordance is offered, not that it is phrased any particular
way.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.lineups import service


@pytest.fixture()
def open_weekend(make_meeting):
    return make_meeting(
        1, deadline_at=datetime.now(timezone.utc) + timedelta(days=7)
    )


def _commit(client, grid, teams=(0, 1, 2, 3), team=4):
    drivers = [grid.driver_at(t).id for t in teams]
    return client.post(
        "/lineup",
        data={"d": ",".join(str(d) for d in drivers), "t": str(grid.teams[team].id)},
        follow_redirects=True,
    )


def test_a_first_lineup_can_be_saved(app, client, signed_in, grid, open_weekend):
    signed_in(email="alice@example.com", username="alice")
    assert _commit(client, grid).status_code == 200
    assert service.snapshot_for(
        db_user(app, "alice"), open_weekend
    ) is not None


def test_editing_a_first_lineup_offers_a_commit(
    app, client, signed_in, grid, open_weekend
):
    """The bug. No earlier snapshot means no cost baseline, but a changed
    draft is still a change worth saving."""
    signed_in(email="alice@example.com", username="alice")
    _commit(client, grid)

    swapped = [grid.driver_at(t).id for t in (0, 1, 2, 5)]
    response = client.get(
        f"/lineup?d={','.join(str(d) for d in swapped)}&t={grid.teams[4].id}"
    )
    assert response.status_code == 200
    assert b"is-disabled" not in response.data


def test_an_unchanged_draft_offers_nothing(
    app, client, signed_in, grid, open_weekend
):
    signed_in(email="alice@example.com", username="alice")
    _commit(client, grid)

    response = client.get("/lineup")
    assert response.status_code == 200
    assert b"is-disabled" in response.data


def test_a_changed_draft_is_actually_stored(
    app, client, signed_in, grid, open_weekend
):
    signed_in(email="alice@example.com", username="alice")
    _commit(client, grid)
    _commit(client, grid, teams=(0, 1, 2, 5))

    snapshot = service.snapshot_for(db_user(app, "alice"), open_weekend)
    assert grid.driver_at(5).id in snapshot.driver_ids
    assert grid.driver_at(3).id not in snapshot.driver_ids


def db_user(app, username):
    from sqlalchemy import select

    from app.extensions import db
    from app.models.user import User

    return db.session.scalar(select(User).where(User.username == username))
