"""Flask CLI commands."""
from __future__ import annotations

import click
from flask.cli import with_appcontext
from sqlalchemy import select

from app.extensions import db
from app.models.user import User


@click.command("set-admin")
@click.argument("email")
@click.option("--revoke", is_flag=True, help="Remove admin rather than grant it.")
@with_appcontext
def set_admin(email: str, revoke: bool) -> None:
    """Grant or revoke admin on an existing account."""
    user = db.session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise click.ClickException(f"No user with email {email!r}.")
    user.is_admin = not revoke
    db.session.commit()
    click.echo(f"{user.username} <{user.email}> is_admin={user.is_admin}")


@click.command("config-check")
@with_appcontext
def config_check() -> None:
    """Print the resolved configuration, with secrets masked.

    Useful on Railway, where the failure mode is an environment variable that
    was never set and silently fell back to a default.
    """
    from flask import current_app

    masked = {"SECRET_KEY", "RESEND_API_KEY", "OCB_API_KEY", "SQLALCHEMY_DATABASE_URI"}
    for key in sorted(current_app.config):
        if key.startswith("_"):
            continue
        value = current_app.config[key]
        if key in masked and value:
            value = f"<set, {len(str(value))} chars>"
        click.echo(f"{key} = {value}")
