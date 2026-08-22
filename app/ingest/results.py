"""Results ingestion.

Fetches session classifications and writes Result rows. Two rules shape this:

  1. **Only qualifying and race sessions are ingested.** Practice teaches the
     game nothing, and `other` covers things like Season 12's Rookie Free
     Practice — a session full of drivers who are not on the grid. Ingesting it
     would put test drivers in the results table and corrupt any "who raced this
     round" query.

  2. **Session status is checked before the request.** A scheduled session has
     nothing to return, so asking costs a call and teaches nothing. The provider
     gives `scheduled | ongoing | completed` on every session.

Idempotent: a session already ingested is skipped unless forced, and re-running
against the same payload produces the same rows.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from app.extensions import db
from app.ingest.checks import verify_championship_points
from app.models.calendar import (
    SCORING_STAGES,
    SESSION_STATUS_COMPLETED,
    STAGE_RACE,
    STAGE_FINAL,
    Round,
    Season,
    Session,
)
from app.models.grid import Driver, Team
from app.models.result import Result
from app.providers.base import ResultRow as ProviderResultRow

log = logging.getLogger(__name__)

# Stages worth fetching, shared with the scoring pass (app/models/calendar.py).
INGESTED_STAGES = SCORING_STAGES


@dataclass
class ResultsReport:
    season_year: int
    sessions_considered: int = 0
    sessions_fetched: int = 0
    sessions_skipped_not_complete: int = 0
    sessions_skipped_already_ingested: int = 0
    # Speculative fetches that came back with nothing. Not an error: the
    # session simply has not been published yet.
    sessions_not_ready: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    drivers_created: int = 0
    teams_created: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return (
            f"season {self.season_year}: "
            f"{self.sessions_fetched} sessions fetched, "
            f"{self.rows_created} rows created, "
            f"{self.rows_updated} updated, "
            f"{self.sessions_skipped_already_ingested} already ingested, "
            f"{self.sessions_skipped_not_complete} not complete, "
            f"{self.sessions_not_ready} not ready, "
            f"{len(self.warnings)} warnings, {len(self.errors)} errors"
        )


# -----------------------------------------------------------------------------
# Reference rows
# -----------------------------------------------------------------------------


def _ensure_driver(ref, report: ResultsReport) -> Driver:
    """Find or create the driver behind a result row.

    Results can name a driver who is absent from the season standings — a
    one-off reserve, most obviously. They still need a row, which is why
    results reference drivers directly rather than seat entries.
    """
    driver = db.session.scalar(
        select(Driver).where(Driver.provider_driver_id == ref.id)
    )
    if driver is None:
        driver = Driver(provider_driver_id=ref.id)
        db.session.add(driver)
        report.drivers_created += 1
    # Standings are the better source for names, so only fill gaps here.
    driver.first_name = driver.first_name or ref.first_name
    driver.last_name = driver.last_name or ref.last_name
    driver.code = driver.code or ref.code
    driver.number = driver.number if driver.number is not None else ref.number
    return driver


def _ensure_team(ref, report: ResultsReport) -> Team | None:
    if ref is None:
        return None
    team = db.session.scalar(select(Team).where(Team.provider_team_id == ref.id))
    if team is None:
        team = Team(provider_team_id=ref.id)
        db.session.add(team)
        report.teams_created += 1
    team.name = team.name or ref.name
    team.short_name = team.short_name or ref.short_name
    team.color = team.color or ref.color
    return team


# -----------------------------------------------------------------------------
# One session
# -----------------------------------------------------------------------------


def _pole_driver_id(round_row: Round) -> str | None:
    """The provider driver id of the Qual Final winner.

    Sessions are ingested in schedule order, so by the time the race is fetched
    the final has already landed. None is fine: the check loosens rather than
    complains.
    """
    return db.session.scalar(
        select(Driver.provider_driver_id)
        .join(Result, Result.driver_id == Driver.id)
        .join(Session, Session.id == Result.session_id)
        .where(
            Session.round_id == round_row.id,
            Session.stage == STAGE_FINAL,
            Result.position == 1,
        )
    )


def sync_session_results(
    provider,
    session_row: Session,
    season: Season,
    report: ResultsReport,
    *,
    force: bool = False,
    speculative: bool = False,
) -> None:
    """Fetch and store one session's classification.

    Commits on success. On failure the session is rolled back and the error
    recorded, so one bad session does not abandon the rest of the round.

    **`speculative` inverts the rule in SPEC.md §6.** That rule — check the
    session's status before requesting results, so a scheduled session costs no
    call — is right for a backfill, where you face 187 sessions and have no idea
    which have run. It is wrong for a live weekend, because status arrives only
    on `/events`, which cannot be filtered by season: refreshing it costs four
    calls, so checking first costs five calls per attempt where guessing costs
    one.

    During a weekend the poller already knows, from the stored schedule, that a
    session was due to finish twenty minutes ago. Asking is the cheap move.

    Two consequences, both handled below. The stored status is stale by
    definition on this path, so it is not consulted. And an empty
    classification means "not ready yet" rather than "ran and nobody
    finished" — so it must not stamp `results_ingested_at`, which would mark an
    unrun session as permanently ingested and silently drop it from the game.
    """
    report.sessions_considered += 1

    if session_row.stage not in INGESTED_STAGES:
        return

    if session_row.results_ingested_at is not None and not force:
        report.sessions_skipped_already_ingested += 1
        return

    if not speculative:
        if (
            session_row.status is not None
            and session_row.status != SESSION_STATUS_COMPLETED
        ):
            report.sessions_skipped_not_complete += 1
            return

    round_row = db.session.get(Round, session_row.round_id)

    try:
        rows = provider.get_results(round_row.provider_event_id, session_row.provider_session_id)
    except Exception as exc:  # provider errors are already classified
        db.session.rollback()
        message = f"R{round_row.round_number} {session_row.name}: {exc}"
        if speculative:
            # A session that has not been published yet may well answer with a
            # 404 rather than an empty array — the provider has never been
            # observed mid-weekend, because Season 12 was already finished when
            # this was written. Either shape means the same thing here: come
            # back later. It is a fact about the schedule, not an error.
            report.sessions_not_ready += 1
            log.debug("Not ready yet: %s", message)
        else:
            report.errors.append(message)
            log.warning("Results fetch failed for %s", message)
        return

    report.sessions_fetched += 1

    if not rows:
        if speculative:
            report.sessions_not_ready += 1
            log.debug(
                "R%s %s returned no rows; not stamping",
                round_row.round_number, session_row.name,
            )
            return
        report.warnings.append(
            f"R{round_row.round_number} {session_row.name}: completed but returned no rows"
        )

    try:
        _write_rows(rows, session_row, season, report)

        pole = _pole_driver_id(round_row) if session_row.stage == STAGE_RACE else None
        for problem in verify_championship_points(
            season.year, session_row.stage, rows, pole
        ):
            report.warnings.append(
                f"R{round_row.round_number} {session_row.name}: {problem}"
            )

        session_row.results_ingested_at = datetime.now(timezone.utc)
        # A speculative fetch that returned a classification has just proved the
        # session ran, whatever the stored status says.
        session_row.status = SESSION_STATUS_COMPLETED
        db.session.commit()

    except Exception as exc:
        db.session.rollback()
        message = f"R{round_row.round_number} {session_row.name}: {exc}"
        report.errors.append(message)
        log.exception("Failed writing results for %s", message)


def _write_rows(
    rows: list[ProviderResultRow],
    session_row: Session,
    season: Season,
    report: ResultsReport,
) -> None:
    for row in rows:
        if row.driver is None:
            report.warnings.append(
                f"{session_row.name}: a result row has no driver; skipped"
            )
            continue

        driver = _ensure_driver(row.driver, report)
        team = _ensure_team(row.team, report)
        db.session.flush()

        existing = db.session.scalar(
            select(Result).where(
                Result.session_id == session_row.id,
                Result.driver_id == driver.id,
            )
        )
        if existing is None:
            existing = Result(
                season_id=season.id,
                session_id=session_row.id,
                provider_result_id=row.id,
                driver_id=driver.id,
            )
            db.session.add(existing)
            report.rows_created += 1
        else:
            report.rows_updated += 1

        existing.provider_result_id = row.id
        existing.team_id = team.id if team else None
        existing.position = row.position
        existing.grid_position = row.grid_position
        existing.status = row.status
        existing.points = row.points
        existing.fastest_lap_rank = row.fastest_lap_rank
        existing.car_number = row.car_number
        existing.lap_time = row.lap_time
        existing.display_time = row.display_time

        if session_row.stage == STAGE_RACE and not existing.has_grid_position:
            # Pit-lane start or a data gap. Places gained/lost will score 0 for
            # this driver rather than guessing a slot, so say so once here.
            report.warnings.append(
                f"{session_row.name}: {driver.short_label} has no grid position "
                f"({row.grid_position!r}); places gained/lost will score 0"
            )


# -----------------------------------------------------------------------------
# Season backfill
# -----------------------------------------------------------------------------


def backfill_season(
    provider,
    ending_year: int,
    *,
    force: bool = False,
    round_numbers: list[int] | None = None,
) -> ResultsReport:
    """Ingest results for every scoring session of a season.

    About ten calls per round — nine qualifying sessions plus the race — so
    roughly 170 for a 17-round season. Comfortably inside the free tier, and the
    only bulk operation this project performs.
    """
    report = ResultsReport(season_year=ending_year)

    season = db.session.scalar(select(Season).where(Season.year == ending_year))
    if season is None:
        report.errors.append(
            f"Season {ending_year} is not in the database. Run sync-season first."
        )
        return report

    stmt = (
        select(Round)
        .where(Round.season_id == season.id)
        .order_by(Round.round_number)
    )
    if round_numbers:
        stmt = stmt.where(Round.round_number.in_(round_numbers))

    for round_row in db.session.scalars(stmt):
        sessions = db.session.scalars(
            select(Session)
            .where(Session.round_id == round_row.id)
            .order_by(Session.ordinal)
        )
        for session_row in sessions:
            sync_session_results(provider, session_row, season, report, force=force)

    log.info("Backfill complete: %s", report.summary())
    return report
