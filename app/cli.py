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

@click.command("sync-season")
@click.argument("ending_year", type=int)
@click.option("--dry-run", is_flag=True, help="Derive and print; write nothing.")
@with_appcontext
def sync_season_command(ending_year: int, dry_run: bool) -> None:
    """Sync a season from the data provider.

    ENDING_YEAR is the year the season finishes: Season 12 is 2026, Season 13
    is 2027. Passing the starting year silently fetches the wrong season.
    """
    from flask import current_app

    from app.ingest.derive import derive_meetings
    from app.ingest.season import SeasonNotPublished, sync_season
    from app.providers.ocblacktop import OCBlacktopProvider

    if not current_app.config.get("OCB_API_KEY"):
        raise click.ClickException("OCB_API_KEY is not set.")

    provider = OCBlacktopProvider.from_config(current_app.config)

    if dry_run:
        season = provider.resolve_season(ending_year)
        if season is None:
            raise click.ClickException(
                f"No season published for ending year {ending_year}."
            )
        detail = provider.get_season_detail(season.id)
        events = provider.events_for_season(detail)
        click.echo(f"{season.year}: {len(events)} events, {len(detail.drivers)} drivers")
        for meeting in derive_meetings(events, detail.season.year):
            rounds = ", ".join(
                f"R{r.round_number} ({r.format})" for r in meeting.rounds
            )
            click.echo(f"  {meeting.sequence:>2}. {meeting.display_name:<16} {rounds}")
        click.echo("Dry run: nothing written.")
        return

    try:
        report = sync_season(provider, ending_year)
    except SeasonNotPublished as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(report.summary())
    for warning in report.warnings:
        click.echo(f"  warning: {warning}")
    for conflict in report.conflicts:
        click.echo(f"  conflict: {conflict}")
    if not report.ok:
        raise SystemExit(1)

@click.command("backfill-results")
@click.argument("ending_year", type=int)
@click.option("--force", is_flag=True, help="Re-ingest sessions already stored.")
@click.option("--round", "round_numbers", type=int, multiple=True,
              help="Limit to specific round numbers. Repeatable.")
@with_appcontext
def backfill_results_command(ending_year: int, force: bool, round_numbers) -> None:
    """Ingest results for a season's qualifying and race sessions.

    Roughly ten calls per round: nine qualifying sessions plus the race. Run
    sync-season first, since this walks the sessions already in the database.
    """
    from flask import current_app

    from app.ingest.results import backfill_season
    from app.providers.ocblacktop import OCBlacktopProvider

    if not current_app.config.get("OCB_API_KEY"):
        raise click.ClickException("OCB_API_KEY is not set.")

    provider = OCBlacktopProvider.from_config(current_app.config)
    report = backfill_season(
        provider, ending_year, force=force,
        round_numbers=list(round_numbers) or None,
    )

    click.echo(report.summary())
    for warning in report.warnings:
        click.echo(f"  warning: {warning}")
    for error in report.errors:
        click.echo(f"  error: {error}")
    if not report.ok:
        raise SystemExit(1)
