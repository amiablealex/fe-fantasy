"""Auth routes: register, login, logout, password reset, account.

Adapted from the F1 Predictions app with the divergences recorded in SPEC.md
§7: no `is_contributor`, registration is rate limited, and there is no invite
consumption yet (the invite blueprint arrives in Phase 6 — the hook point is
marked below).
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select

from app.auth import rate_limit
from app.auth.email import send_password_reset_email
from app.auth.forms import (
    ChangeEmailForm,
    ChangePasswordForm,
    ChangeUsernameForm,
    DeleteAccountForm,
    ForgotPasswordForm,
    LoginForm,
    RegisterForm,
    ResetPasswordForm,
)
from app.extensions import db
from app.models.user import PasswordResetToken, User
from app.utils import client_ip

auth_bp = Blueprint("auth", __name__, template_folder="../templates")

BUCKET_LOGIN = "login"
BUCKET_REGISTER = "register"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _is_safe_redirect(target: str | None) -> bool:
    """Allow only same-host, path-relative redirects after login."""
    if not target:
        return False
    parsed = urlparse(target)
    return parsed.scheme == "" and parsed.netloc == "" and target.startswith("/")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _client_key() -> str:
    return client_ip()


def _blocked_response(bucket: str, template: str, form, title: str):
    """Render a rate-limited response, or None if not blocked."""
    key = _client_key()
    if not rate_limit.is_blocked(bucket, key):
        return None
    wait = rate_limit.retry_after_seconds(bucket, key)
    minutes = max(1, (wait + 59) // 60)
    flash(f"Too many attempts. Try again in {minutes} minute(s).", "error")
    return render_template(template, form=form, title=title), 429


def _flash_form_errors(form) -> None:
    for errors in form.errors.values():
        for err in errors:
            flash(err, "error")


# -----------------------------------------------------------------------------
# Register
# -----------------------------------------------------------------------------


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("lineups.home"))

    form = RegisterForm()

    if request.method == "POST":
        blocked = _blocked_response(
            BUCKET_REGISTER, "auth/register.html", form, "Create account"
        )
        if blocked is not None:
            return blocked

    if form.validate_on_submit():
        user = User(
            email=form.email.data.strip().lower(),
            username=form.username.data.strip(),
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        login_user(user, remember=True)
        user.last_login_at = _utcnow()
        user.last_seen_at = user.last_login_at
        db.session.commit()

        rate_limit.reset(BUCKET_REGISTER, _client_key())

        # Phase 6 hook: consume a pending league invite here.
        flash("Account created — welcome.", "success")
        return redirect(url_for("lineups.home"))

    if request.method == "POST":
        # Count only genuine failures, so a mistyped password does not lock a
        # legitimate visitor out for an hour on the first attempt.
        cfg = current_app.config
        rate_limit.record_failure(
            BUCKET_REGISTER,
            _client_key(),
            max_attempts=cfg["REGISTER_MAX_ATTEMPTS"],
            window_minutes=cfg["REGISTER_WINDOW_MINUTES"],
            block_minutes=cfg["REGISTER_BLOCK_MINUTES"],
        )

    return render_template("auth/register.html", form=form, title="Create account")


# -----------------------------------------------------------------------------
# Login / logout
# -----------------------------------------------------------------------------


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("lineups.home"))

    form = LoginForm()

    if request.method == "POST":
        blocked = _blocked_response(BUCKET_LOGIN, "auth/login.html", form, "Sign in")
        if blocked is not None:
            return blocked

    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = db.session.scalar(select(User).where(User.email == email))
        if user is None or not user.check_password(form.password.data):
            cfg = current_app.config
            rate_limit.record_failure(
                BUCKET_LOGIN,
                _client_key(),
                max_attempts=cfg["LOGIN_MAX_ATTEMPTS"],
                window_minutes=cfg["LOGIN_WINDOW_MINUTES"],
                block_minutes=cfg["LOGIN_BLOCK_MINUTES"],
            )
            flash("Email or password incorrect.", "error")
            return render_template("auth/login.html", form=form, title="Sign in"), 401

        rate_limit.reset(BUCKET_LOGIN, _client_key())
        login_user(user, remember=form.remember.data)
        user.last_login_at = _utcnow()
        user.last_seen_at = user.last_login_at
        db.session.commit()

        # Phase 6 hook: consume a pending league invite here.
        next_url = request.args.get("next")
        if _is_safe_redirect(next_url):
            return redirect(next_url)
        return redirect(url_for("lineups.home"))

    return render_template("auth/login.html", form=form, title="Sign in")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("auth.login"))


# -----------------------------------------------------------------------------
# Forgot / reset password
# -----------------------------------------------------------------------------


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("lineups.home"))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = db.session.scalar(select(User).where(User.email == email))
        if user is not None:
            ttl = current_app.config["PASSWORD_RESET_TOKEN_TTL_HOURS"]
            token = PasswordResetToken.issue(user=user, ttl_hours=ttl)
            db.session.add(token)
            db.session.commit()
            send_password_reset_email(user, token)
        # Identical response whether or not the account exists.
        flash("If an account exists for that email, a reset link is on its way.", "info")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html", form=form, title="Forgot password")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    if current_user.is_authenticated:
        return redirect(url_for("lineups.home"))

    reset_token = db.session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token == token)
    )
    if reset_token is None or not reset_token.is_valid:
        flash("That reset link is invalid or has expired.", "error")
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        reset_token.user.set_password(form.password.data)
        reset_token.consume()
        db.session.commit()
        flash("Password updated. You can now sign in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", form=form, title="Reset password")


# -----------------------------------------------------------------------------
# Account
# -----------------------------------------------------------------------------


@auth_bp.route("/account", methods=["GET"])
@login_required
def account():
    return render_template(
        "auth/account.html",
        username_form=ChangeUsernameForm(
            current_user_id=current_user.id, username=current_user.username
        ),
        email_form=ChangeEmailForm(current_user_id=current_user.id, email=current_user.email),
        password_form=ChangePasswordForm(),
        delete_form=DeleteAccountForm(),
        title="Account",
    )


@auth_bp.route("/account/username", methods=["POST"])
@login_required
def change_username():
    form = ChangeUsernameForm(current_user_id=current_user.id)
    if form.validate_on_submit():
        current_user.username = form.username.data.strip()
        db.session.commit()
        flash("Display name updated.", "success")
    else:
        _flash_form_errors(form)
    return redirect(url_for("auth.account"))


@auth_bp.route("/account/email", methods=["POST"])
@login_required
def change_email():
    form = ChangeEmailForm(current_user_id=current_user.id)
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password incorrect.", "error")
            return redirect(url_for("auth.account"))
        current_user.email = form.email.data.strip().lower()
        db.session.commit()
        flash("Email updated.", "success")
    else:
        _flash_form_errors(form)
    return redirect(url_for("auth.account"))


@auth_bp.route("/account/password", methods=["POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password incorrect.", "error")
            return redirect(url_for("auth.account"))
        current_user.set_password(form.new_password.data)
        db.session.commit()
        flash("Password updated.", "success")
    else:
        _flash_form_errors(form)
    return redirect(url_for("auth.account"))


@auth_bp.route("/account/delete", methods=["POST"])
@login_required
def delete_account():
    form = DeleteAccountForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password incorrect.", "error")
            return redirect(url_for("auth.account"))

        user_id = current_user.id
        logout_user()
        user = db.session.get(User, user_id)
        if user is not None:
            db.session.delete(user)
            db.session.commit()
        flash("Account deleted. Goodbye.", "info")
        return redirect(url_for("auth.login"))

    _flash_form_errors(form)
    return redirect(url_for("auth.account"))
