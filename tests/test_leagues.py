"""League lifecycle: create, join, leave, administer, hide.

The cases worth having are the ones a naive implementation gets wrong: the cap
under concurrency, a league losing its last admin, the global league refusing
things that look like ordinary operations, and an invite that expires in the
session rather than sitting there for a month.
"""
from __future__ import annotations

import time

import pytest
from sqlalchemy.exc import IntegrityError

from app.leagues import invite, service
from app.models.league import ROLE_ADMIN, ROLE_MEMBER, LeagueMembership


@pytest.fixture()
def alice(make_user):
    return make_user(email="alice@example.com", username="alice")


@pytest.fixture()
def bob(make_user):
    return make_user(email="bob@example.com", username="bob")


# -----------------------------------------------------------------------------
# Creating
# -----------------------------------------------------------------------------


def test_creating_a_league_makes_the_creator_admin(app, alice):
    league = service.create_league(alice, "Friends")
    membership = service.membership_of(alice, league)
    assert membership.role == ROLE_ADMIN
    assert league.created_by_id == alice.id


def test_a_created_league_gets_a_usable_code(app, alice):
    league = service.create_league(alice, "Friends")
    assert len(league.invite_code) == app.config["INVITE_CODE_LENGTH"]
    assert service.league_by_code(league.invite_code.lower()).id == league.id


def test_a_blank_name_is_refused(app, alice):
    with pytest.raises(service.LeagueError):
        service.create_league(alice, "   ")


# -----------------------------------------------------------------------------
# Joining
# -----------------------------------------------------------------------------


def test_joining_by_code(app, alice, bob):
    league = service.create_league(alice, "Friends")
    service.join_league(bob, league)
    assert service.membership_of(bob, league).role == ROLE_MEMBER
    assert service.member_count(league) == 2


def test_joining_twice_is_refused(app, alice, bob):
    league = service.create_league(alice, "Friends")
    service.join_league(bob, league)
    with pytest.raises(service.LeagueError):
        service.join_league(bob, league)


def test_the_cap_is_enforced(app, alice, make_user, db):
    app.config["MAX_LEAGUE_MEMBERS"] = 3
    league = service.create_league(alice, "Small")
    service.join_league(make_user(email="b@x.com", username="b"), league)
    service.join_league(make_user(email="c@x.com", username="c"), league)

    with pytest.raises(service.LeagueError):
        service.join_league(make_user(email="d@x.com", username="d"), league)
    assert service.member_count(league) == 3


def test_the_cap_does_not_apply_to_the_global_league(app, alice, bob):
    app.config["MAX_LEAGUE_MEMBERS"] = 1
    service.ensure_global_membership(alice)
    service.ensure_global_membership(bob)
    assert service.member_count(service.global_league()) == 2
    assert not service.is_full(service.global_league())


def test_the_global_sentinel_is_not_a_joinable_code(app, alice):
    service.ensure_global_league()
    assert service.league_by_code("GLOBAL") is None


# -----------------------------------------------------------------------------
# Leaving and removing
# -----------------------------------------------------------------------------


def test_leaving_removes_the_membership(app, alice, bob):
    league = service.create_league(alice, "Friends")
    service.join_league(bob, league)
    service.leave_league(bob, league)
    assert service.membership_of(bob, league) is None


def test_the_last_admin_leaving_promotes_a_successor(app, alice, bob):
    """A league with members and no admin has nobody who can administer it,
    and nothing anywhere to explain why."""
    league = service.create_league(alice, "Friends")
    service.join_league(bob, league)
    service.leave_league(alice, league)
    assert service.membership_of(bob, league).is_admin


def test_the_global_league_cannot_be_left(app, alice):
    service.ensure_global_membership(alice)
    with pytest.raises(service.LeagueError):
        service.leave_league(alice, service.global_league())


def test_an_admin_can_remove_a_member(app, alice, bob):
    league = service.create_league(alice, "Friends")
    service.join_league(bob, league)
    service.remove_member(alice, league, bob)
    assert service.membership_of(bob, league) is None


def test_a_member_cannot_remove_anyone(app, alice, bob):
    league = service.create_league(alice, "Friends")
    service.join_league(bob, league)
    with pytest.raises(service.LeagueError):
        service.remove_member(bob, league, alice)


def test_an_admin_cannot_remove_themselves(app, alice, bob):
    league = service.create_league(alice, "Friends")
    service.join_league(bob, league)
    with pytest.raises(service.LeagueError):
        service.remove_member(alice, league, alice)


# -----------------------------------------------------------------------------
# Administering
# -----------------------------------------------------------------------------


def test_rotating_the_code_kills_the_old_one(app, alice):
    league = service.create_league(alice, "Friends")
    old = league.invite_code
    service.rotate_invite_code(alice, league)
    assert league.invite_code != old
    assert service.league_by_code(old) is None
    assert service.league_by_code(league.invite_code).id == league.id


def test_a_member_cannot_rotate_or_rename(app, alice, bob):
    league = service.create_league(alice, "Friends")
    service.join_league(bob, league)
    with pytest.raises(service.LeagueError):
        service.rotate_invite_code(bob, league)
    with pytest.raises(service.LeagueError):
        service.rename_league(bob, league, "Bob's League")


def test_the_global_league_cannot_be_renamed_or_rotated(app, alice):
    league = service.ensure_global_league()
    with pytest.raises(service.LeagueError):
        service.rename_league(alice, league, "Something else")
    with pytest.raises(service.LeagueError):
        service.rotate_invite_code(alice, league)


# -----------------------------------------------------------------------------
# Hiding
# -----------------------------------------------------------------------------


def test_hiding_keeps_the_membership(app, alice):
    service.set_global_hidden(alice, True)
    membership = service.membership_of(alice, service.global_league())
    assert membership is not None
    assert membership.hidden is True
    assert service.is_hidden_globally(alice)


def test_unhiding(app, alice):
    service.set_global_hidden(alice, True)
    service.set_global_hidden(alice, False)
    assert not service.is_hidden_globally(alice)


# -----------------------------------------------------------------------------
# Pending invites
# -----------------------------------------------------------------------------


def test_a_pending_invite_expires(app, alice):
    league = service.create_league(alice, "Friends")
    with app.test_request_context():
        invite.remember(league.invite_code)
        app.config["PENDING_INVITE_TTL_MINUTES"] = 0
        time.sleep(0.01)
        assert invite.take() is None


def test_a_pending_invite_survives_within_its_ttl(app, alice):
    league = service.create_league(alice, "Friends")
    with app.test_request_context():
        invite.remember(league.invite_code)
        assert invite.take() == league.invite_code


def test_consuming_an_invite_joins_the_league(app, alice, bob):
    league = service.create_league(alice, "Friends")
    with app.test_request_context():
        invite.remember(league.invite_code)
        outcome = invite.consume(bob)
    assert outcome.joined
    assert service.membership_of(bob, league) is not None


def test_consuming_a_dead_invite_reports_rather_than_raises(app, bob):
    with app.test_request_context():
        invite.remember("ZZZZZZ")
        outcome = invite.consume(bob)
    assert not outcome.joined
    assert outcome.message


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


def test_a_non_member_gets_404_not_403(app, client, signed_in, make_user):
    """403 would confirm the league exists."""
    owner = make_user(email="owner@example.com", username="owner")
    league = service.create_league(owner, "Private")
    signed_in(email="nosy@example.com", username="nosy")

    response = client.get(f"/leagues/{league.id}")
    assert response.status_code == 404


def test_the_leagues_page_lists_the_global_league(app, client, signed_in):
    user = signed_in(email="alice@example.com", username="alice")
    service.ensure_global_membership(user)
    response = client.get("/leagues/")
    assert response.status_code == 200
    assert b"FE Fantasy" in response.data


def test_an_invite_link_joins_a_signed_in_visitor(
    app, client, signed_in, make_user
):
    owner = make_user(email="owner@example.com", username="owner")
    league = service.create_league(owner, "Friends")
    user = signed_in(email="alice@example.com", username="alice")

    response = client.get(f"/join/{league.invite_code}", follow_redirects=True)
    assert response.status_code == 200
    assert service.membership_of(user, league) is not None


def test_an_unknown_invite_link_is_404_for_a_visitor(app, client):
    response = client.get("/join/ZZZZZZ")
    assert response.status_code == 404


def test_registering_enrols_in_the_global_league(app, client):
    response = client.post(
        "/auth/register",
        data={
            "email": "new@example.com",
            "username": "newbie",
            "password": "password1",
            "confirm_password": "password1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    from sqlalchemy import select

    from app.extensions import db
    from app.models.user import User

    user = db.session.scalar(select(User).where(User.email == "new@example.com"))
    assert user is not None
    assert service.membership_of(user, service.global_league()) is not None


def test_a_membership_row_is_unique_per_league(app, alice, db):
    league = service.create_league(alice, "Friends")
    db.session.add(LeagueMembership(league_id=league.id, user_id=alice.id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
