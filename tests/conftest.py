"""Test fixtures.

Tests run against a real Postgres database (TEST_DATABASE_URL), not SQLite.
The production database is Postgres 18.4 in both environments, and a test suite
that passes on a different engine is a test suite that tells you less than it
appears to.
"""
from __future__ import annotations
from types import SimpleNamespace
from decimal import Decimal

import pytest

from app import create_app
from app.auth import rate_limit
from app.config import TestingConfig
from app.extensions import db as _db
from app.models.user import User
from app.models.calendar import Location, Meeting, Round, Season
from app.models.grid import Driver, SeatEntry, Team
from app.models.league import League, LeagueMembership
from app.models.lineup import LineupSnapshot
from app.models.score import RoundScore, PickScore
from app.scoring import lineups as rules

@pytest.fixture()
def app():
    application = create_app(TestingConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture(autouse=True)
def _clear_rate_limits():
    """Rate limit state is module-level, so it leaks between tests."""
    rate_limit.clear_all()
    yield
    rate_limit.clear_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def make_user(db):
    def _make(email="racer@example.com", username="racer", password="password1", is_admin=False):
        user = User(email=email, username=username, is_admin=is_admin)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    return _make


@pytest.fixture()
def signed_in(client, make_user):
    def _sign_in(**kwargs):
        password = kwargs.pop("password", "password1")
        user = make_user(password=password, **kwargs)
        response = client.post(
            "/auth/login",
            data={"email": user.email, "password": password},
            follow_redirects=True,
        )
        assert response.status_code == 200
        return user

    return _sign_in


@pytest.fixture()
def season(db):
    """Season 13, keyed by its ENDING year (SPEC.md §6)."""
    record = Season(
        provider_season_id="season-uuid-2027", year=2027, display_name="Season 13"
    )
    db.session.add(record)
    db.session.commit()
    return record


@pytest.fixture()
def grid(db, season):
    """Ten teams of two drivers, seated for every round.

    The current grid's shape, and therefore the shape the lineup rules are
    sized against: C(10,4) x 2^4 x 6 = 20,160 valid lineups. Never assumed
    anywhere in `app/scoring/` — reproduced here because it is what the tests
    need to be about.
    """
    teams = [
        Team(
            provider_team_id=f"team-{i}",
            name=f"Team {chr(65 + i)}",
            short_name=f"T{chr(65 + i)}",
        )
        for i in range(10)
    ]
    db.session.add_all(teams)
    db.session.flush()

    drivers = []
    for team_index, team in enumerate(teams):
        for car in range(2):
            number = team_index * 2 + car + 1
            driver = Driver(
                provider_driver_id=f"driver-{number}",
                first_name="Test",
                last_name=f"Driver{number:02d}",
                number=number,
            )
            db.session.add(driver)
            db.session.flush()
            db.session.add(SeatEntry(
                season_id=season.id,
                driver_id=driver.id,
                team_id=team.id,
                participation_rounds=list(range(1, 22)),
            ))
            drivers.append(driver)
    db.session.commit()

    def driver_at(team_index: int, car: int = 0) -> Driver:
        return drivers[team_index * 2 + car]

    def lineup(driver_teams=(0, 1, 2, 3), team=4, cars=(0, 0, 0, 0)) -> rules.Lineup:
        """A valid lineup by team index, so a test can state its intent.

        Defaults are legal: four drivers from four teams, and a fifth team in
        the team slot.
        """
        return rules.Lineup.of(
            [driver_at(t, c).id for t, c in zip(driver_teams, cars)],
            teams[team].id,
        )

    return SimpleNamespace(
        teams=teams, drivers=drivers, driver_at=driver_at, lineup=lineup
    )


@pytest.fixture()
def make_meeting(db, season):
    """A meeting with its rounds, at a fresh location.

    `rounds` of 2 makes a double-header, which is the case worth testing:
    one lineup, one deadline, two scoring rounds.
    """
    state = {"round_number": 0}

    def _make(sequence: int, deadline_at=None, rounds: int = 1) -> Meeting:
        location = Location(
            provider_location_id=f"loc-{sequence}",
            name=f"Venue {sequence}",
            city=f"City {sequence}",
        )
        db.session.add(location)
        db.session.flush()

        meeting = Meeting(
            season_id=season.id,
            location_id=location.id,
            sequence=sequence,
            display_name=f"City {sequence}",
            deadline_at=deadline_at,
        )
        db.session.add(meeting)
        db.session.flush()

        for index in range(rounds):
            state["round_number"] += 1
            db.session.add(Round(
                season_id=season.id,
                meeting_id=meeting.id,
                provider_event_id=f"event-{state['round_number']}",
                round_number=state["round_number"],
                number_in_meeting=index + 1,
                scoring_ruleset_version="v1",
            ))
        db.session.commit()
        return meeting

    return _make


@pytest.fixture()
def make_league(db):
    """A league with its members already enrolled.

    Codes are sequential rather than generated: a test that fails because two
    random six-character codes collided would be maddening to diagnose and
    proves nothing about the code the application actually generates.
    """
    state = {"n": 0}

    def _make(name="Test League", members=(), is_global=False):
        state["n"] += 1
        league = League(
            name=name,
            invite_code=f"TEST{state['n']:03d}",
            is_global=is_global,
        )
        db.session.add(league)
        db.session.flush()
        for user in members:
            db.session.add(
                LeagueMembership(league_id=league.id, user_id=user.id)
            )
        db.session.commit()
        return league

    return _make


@pytest.fixture()
def make_snapshot(db):
    """A committed lineup, written directly.

    Not through `service.commit`, deliberately: that enforces the open weekend
    and the transfer budget, and a visibility test needs a lineup at a meeting
    that has already locked — which commit will never write.
    """
    def _make(user, meeting, lineup, transfer_cost=0):
        record = LineupSnapshot.build(
            user_id=user.id,
            season_id=meeting.season_id,
            meeting_id=meeting.id,
            lineup=lineup,
            transfer_cost=transfer_cost,
        )
        db.session.add(record)
        db.session.commit()
        return record

    return _make

@pytest.fixture()
def award(db, grid, make_snapshot):
    """Give a user points at a meeting, with the score rows behind them.

    A `PickScore` is not a free-standing number — it points at the snapshot
    that earned it and the `RoundScore` it came from, and both are NOT NULL.
    Writing a bare PickScore in a test would exercise a row shape the scoring
    pass can never produce.

    Each user is assigned their own driver so the `(round, driver)` uniqueness
    on RoundScore holds while two players score differently at the same
    weekend.
    """
    seats = {}

    def _award(user, meeting, points):
        if user.id not in seats:
            seats[user.id] = grid.drivers[len(seats)]
        driver = seats[user.id]
        round_obj = meeting.rounds[0]
        amount = Decimal(points)

        snapshot = make_snapshot(user, meeting, grid.lineup())

        score = RoundScore(
            season_id=meeting.season_id,
            round_id=round_obj.id,
            kind="driver",
            driver_id=driver.id,
            points=amount,
            breakdown=[],
            participated=True,
            ruleset_version="v1",
        )
        db.session.add(score)
        db.session.flush()

        db.session.add(PickScore(
            user_id=user.id,
            season_id=meeting.season_id,
            meeting_id=meeting.id,
            round_id=round_obj.id,
            snapshot_id=snapshot.id,
            round_score_id=score.id,
            kind="driver",
            driver_id=driver.id,
            points=amount,
        ))
        db.session.commit()
        return score

    return _award
