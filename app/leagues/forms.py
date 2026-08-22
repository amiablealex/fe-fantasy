"""League forms.

Short. The only field with any thought in it is the invite code, which is
uppercased and stripped on the way in because a code arrives typed on a phone
as often as tapped from a link, and `type="text"` with `inputmode` beats a
picky validator for that (SPEC.md §11).
"""
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class CreateLeagueForm(FlaskForm):
    name = StringField(
        "League name", validators=[DataRequired(), Length(min=2, max=80)]
    )
    submit = SubmitField("Create league")


class RenameLeagueForm(FlaskForm):
    name = StringField(
        "League name", validators=[DataRequired(), Length(min=2, max=80)]
    )
    submit = SubmitField("Rename")


class JoinLeagueForm(FlaskForm):
    code = StringField(
        "Invite code", validators=[DataRequired(), Length(min=4, max=16)]
    )
    submit = SubmitField("Join")

    def filter_code(self, value):
        """A WTForms inline filter, not a helper.

        `filter_<fieldname>` is a framework hook, the same as
        `validate_<fieldname>`, so this runs at process time and `code.data` is
        already normalised by the time anything reads it. It was originally
        written as a method the route called, which WTForms found and invoked
        with the field value — a 500 on a GET.
        """
        return (value or "").strip().upper()


class GlobalVisibilityForm(FlaskForm):
    """The account toggle.

    Phrased positively — "show me" rather than "hide me" — because a checkbox
    that is checked by default and means "do not" is read wrong by everyone.
    """

    show = BooleanField("Show me on the global league table")
    submit = SubmitField("Save")
