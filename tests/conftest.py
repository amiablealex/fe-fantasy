"""Test fixtures.

Tests run against a real Postgres database (TEST_DATABASE_URL), not SQLite.
The production database is Postgres 18.4 in both environments, and a test suite
that passes on a different engine is a test suite that tells you less than it
appears to.
"""
from __future__ import annotations

import pytest

from app import create_app
from app.auth import rate_limit
from app.config import TestingConfig
from app.extensions import db as _db
from app.models.user import User


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
