"""Auth flow tests.

Deliberately covers the security-relevant behaviour rather than the happy path
alone: enumeration resistance, redirect safety, and rate limiting.
"""
from __future__ import annotations

from app.auth import rate_limit
from app.auth.routes import _is_safe_redirect
from sqlalchemy import select

from app.models.user import PasswordResetToken, User


def _register(client, **overrides):
    data = {
        "email": "new@example.com",
        "username": "newcomer",
        "password": "password1",
        "confirm_password": "password1",
    }
    data.update(overrides)
    return client.post("/auth/register", data=data, follow_redirects=True)


def test_register_creates_a_user_and_signs_them_in(client, db):
    response = _register(client)
    assert response.status_code == 200
    user = db.session.scalars(select(User).where(User.email == "new@example.com")).one()
    assert user.check_password("password1")
    assert user.last_seen_at is not None

    # Signed in: the account page is reachable without a further login.
    assert client.get("/auth/account").status_code == 200


def test_register_rejects_a_duplicate_email(client, make_user):
    make_user(email="taken@example.com", username="taken")
    response = _register(client, email="taken@example.com")
    assert b"already exists" in response.data


def test_login_rejects_a_wrong_password(client, make_user):
    make_user()
    response = client.post(
        "/auth/login", data={"email": "racer@example.com", "password": "wrong-password1"}
    )
    assert response.status_code == 401


def test_login_succeeds_and_records_timestamps(client, db, make_user):
    make_user()
    response = client.post(
        "/auth/login",
        data={"email": "racer@example.com", "password": "password1"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    user = db.session.scalars(select(User).where(User.email == "racer@example.com")).one()
    assert user.last_login_at is not None
    assert user.last_seen_at is not None


def test_login_is_blocked_after_repeated_failures(client, app, make_user):
    make_user()
    limit = app.config["LOGIN_MAX_ATTEMPTS"]
    for _ in range(limit):
        client.post("/auth/login", data={"email": "racer@example.com", "password": "nope1234"})
    response = client.post(
        "/auth/login", data={"email": "racer@example.com", "password": "password1"}
    )
    assert response.status_code == 429


def test_forgot_password_response_does_not_reveal_whether_the_account_exists(client, make_user):
    make_user(email="known@example.com", username="known")
    known = client.post(
        "/auth/forgot-password", data={"email": "known@example.com"}, follow_redirects=True
    )
    unknown = client.post(
        "/auth/forgot-password", data={"email": "nobody@example.com"}, follow_redirects=True
    )
    assert known.status_code == unknown.status_code == 200
    assert b"reset link is on its way" in known.data
    assert b"reset link is on its way" in unknown.data


def test_reset_token_is_single_use(client, db, app, make_user):
    user = make_user()
    token = PasswordResetToken.issue(user=user, ttl_hours=2)
    db.session.add(token)
    db.session.commit()
    raw = token.token

    first = client.post(
        f"/auth/reset-password/{raw}",
        data={"password": "newpassword1", "confirm_password": "newpassword1"},
        follow_redirects=True,
    )
    assert b"Password updated" in first.data

    second = client.get(f"/auth/reset-password/{raw}", follow_redirects=True)
    assert b"invalid or has expired" in second.data


def test_account_page_requires_authentication(client):
    response = client.get("/auth/account")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_delete_account_removes_the_user(client, db, signed_in):
    signed_in()
    response = client.post(
        "/auth/account/delete",
        data={"current_password": "password1", "confirm_phrase": "delete my account"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert db.session.scalar(select(User).where(User.email == "racer@example.com")) is None


def test_deleting_an_account_does_not_break_on_a_league_it_created(client, db, signed_in):
    """The F1 app raises IntegrityError here: its FK is NOT NULL and RESTRICT."""
    from app.models.league import League

    user = signed_in()
    db.session.add(League(name="Test League", invite_code="ABC123", created_by_id=user.id))
    db.session.commit()

    response = client.post(
        "/auth/account/delete",
        data={"current_password": "password1", "confirm_phrase": "delete my account"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    league = db.session.scalars(select(League).where(League.invite_code == "ABC123")).one()
    assert league.created_by_id is None


def test_admin_page_is_forbidden_to_a_normal_user(client, signed_in):
    signed_in()
    assert client.get("/admin/").status_code == 403


def test_admin_page_is_reachable_by_an_admin(client, signed_in):
    signed_in(is_admin=True)
    response = client.get("/admin/")
    # Authorisation only. Asserting on the page's wording is what broke this
    # when Phase 5 restyled the admin templates, and a 200 from a route behind
    # `admin_required` is the whole claim being made here.
    assert response.status_code == 200


def test_safe_redirect_rejects_offsite_targets():
    assert _is_safe_redirect("/lineup") is True
    assert _is_safe_redirect("https://evil.example.com/") is False
    assert _is_safe_redirect("//evil.example.com/") is False
    assert _is_safe_redirect("") is False
    assert _is_safe_redirect(None) is False


def test_rate_limit_resets_on_success(app, make_user, client):
    make_user()
    client.post("/auth/login", data={"email": "racer@example.com", "password": "nope1234"})
    client.post(
        "/auth/login",
        data={"email": "racer@example.com", "password": "password1"},
        follow_redirects=True,
    )
    assert rate_limit.is_blocked("login", "127.0.0.1") is False
