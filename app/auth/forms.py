"""WTForms for the auth blueprint.

Validation philosophy: friendly to a friend-group app. Email-based login,
8-character minimum, no fussy complexity rules — current NIST guidance is that
length beats character-class theatre.
"""
from __future__ import annotations

import re

from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp, ValidationError

from app.extensions import db
from app.models.user import User

USERNAME_PATTERN = r"^[A-Za-z0-9_.\-]+$"
_DIGIT_RE = re.compile(r"\d")


def _exists(stmt, exclude_user_id: int | None) -> bool:
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return db.session.execute(stmt.limit(1)).first() is not None


def _username_taken(username: str, exclude_user_id: int | None = None) -> bool:
    return _exists(select(User.id).where(User.username == username), exclude_user_id)


def _email_taken(email: str, exclude_user_id: int | None = None) -> bool:
    return _exists(select(User.id).where(User.email == email.lower()), exclude_user_id)


def _validate_password_strength(_form, field):
    pw = field.data or ""
    if len(pw) < 8:
        raise ValidationError("At least 8 characters.")
    if not _DIGIT_RE.search(pw):
        raise ValidationError("Include at least one digit.")


class RegisterForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[DataRequired(), Email(message="Enter a valid email."), Length(max=255)],
    )
    username = StringField(
        "Display name",
        validators=[
            DataRequired(),
            Length(min=2, max=50, message="2-50 characters."),
            Regexp(USERNAME_PATTERN, message="Letters, numbers, dot, dash and underscore only."),
        ],
    )
    password = PasswordField("Password", validators=[DataRequired(), _validate_password_strength])
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords don't match.")],
    )
    submit = SubmitField("Create account")

    def validate_email(self, field):
        if _email_taken(field.data.strip().lower()):
            raise ValidationError("An account with that email already exists.")

    def validate_username(self, field):
        if _username_taken(field.data.strip()):
            raise ValidationError("That display name is taken.")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Stay signed in", default=True)
    submit = SubmitField("Sign in")


class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Send reset link")


class ResetPasswordForm(FlaskForm):
    password = PasswordField("New password", validators=[DataRequired(), _validate_password_strength])
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("password", message="Passwords don't match.")],
    )
    submit = SubmitField("Update password")


class ChangeUsernameForm(FlaskForm):
    username = StringField(
        "Display name",
        validators=[DataRequired(), Length(min=2, max=50), Regexp(USERNAME_PATTERN)],
    )
    submit = SubmitField("Update display name")

    def __init__(self, *args, current_user_id: int | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_user_id = current_user_id

    def validate_username(self, field):
        if _username_taken(field.data.strip(), exclude_user_id=self._current_user_id):
            raise ValidationError("That display name is taken.")


class ChangeEmailForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    current_password = PasswordField("Current password", validators=[DataRequired()])
    submit = SubmitField("Update email")

    def __init__(self, *args, current_user_id: int | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_user_id = current_user_id

    def validate_email(self, field):
        if _email_taken(field.data.strip().lower(), exclude_user_id=self._current_user_id):
            raise ValidationError("An account with that email already exists.")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired()])
    new_password = PasswordField("New password", validators=[DataRequired(), _validate_password_strength])
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords don't match.")],
    )
    submit = SubmitField("Update password")


class DeleteAccountForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired()])
    confirm_phrase = StringField('Type "delete my account" to confirm', validators=[DataRequired()])
    submit = SubmitField("Delete account permanently")

    def validate_confirm_phrase(self, field):
        if field.data.strip().lower() != "delete my account":
            raise ValidationError('Type the phrase exactly: "delete my account".')
