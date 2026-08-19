"""Read-only queries backing the styleguide.

Every one of these is a plain SQLAlchemy 2.x `select()` against the ingestion
models, so the styleguide renders whatever is actually in the database. That is
the point: a design that works against fixtures and fails against `Müller` at
width 62 in a real classification has not been tested.

Nothing here writes, and nothing here is imported by the application.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.calendar import (
    STAGE_FINAL,
    STAGE_RACE,
    Round,
    Season,
    Session,
)
from app.models.grid import Driver, SeatEntry, Team
from app.models.result import Result

# Season 12 is keyed by its ENDING year (SPEC.md §6).
DEFAULT_SEASON_YEAR = 2026


def get_season(year: int = DEFAULT_SEASON_YEAR) -> Season | None:
    return db.session.scalar(select(Season).where(Season.year == year))


def teams() -> list[Team]:
    return list(db.session.scalars(select(Team).order_by(Team.name)))


def seats(season: Season) -> list[SeatEntry]:
    """Seat entries for the picker: driver, team, and rounds participated.

    Ordered by surname, which is how a picker is scanned. Note this is the
    pickable roster (SPEC.md §2) — derived from seats, not from results, so a
    rookie-practice-only driver correctly does not appear.
    """
    stmt = (
        select(SeatEntry)
        .where(SeatEntry.season_id == season.id)
        .options(joinedload(SeatEntry.driver), joinedload(SeatEntry.team))
        .join(Driver, SeatEntry.driver_id == Driver.id)
        .order_by(Driver.last_name, Driver.first_name)
    )
    return list(db.session.scalars(stmt).unique())


def rounds(season: Season) -> list[Round]:
    stmt = (
        select(Round)
        .where(Round.season_id == season.id)
        .options(joinedload(Round.meeting))
        .order_by(Round.round_number)
    )
    return list(db.session.scalars(stmt).unique())


def _results_for_stage(season: Season, round_number: int, stage: str) -> list[Result]:
    stmt = (
        select(Result)
        .join(Session, Result.session_id == Session.id)
        .join(Round, Session.round_id == Round.id)
        .where(
            Round.season_id == season.id,
            Round.round_number == round_number,
            Session.stage == stage,
        )
        .options(joinedload(Result.driver), joinedload(Result.team))
        .order_by(Result.position)
    )
    return list(db.session.scalars(stmt).unique())


def race_classification(season: Season, round_number: int) -> list[Result]:
    return _results_for_stage(season, round_number, STAGE_RACE)


def qualifying_final(season: Season, round_number: int) -> list[Result]:
    """The two drivers in the Qual Final. Pole is the winner here, never
    whoever starts P1 (SPEC.md §3)."""
    return _results_for_stage(season, round_number, STAGE_FINAL)


def get_round(season: Season, round_number: int) -> Round | None:
    stmt = (
        select(Round)
        .where(Round.season_id == season.id, Round.round_number == round_number)
        .options(joinedload(Round.meeting))
    )
    return db.session.scalars(stmt).unique().one_or_none()


def season_leaders(season: Season, limit: int = 12) -> list[tuple[Driver, float]]:
    """Real championship points by driver, purely as a source of realistic
    figures for the standings pattern.

    This is NOT the fantasy table — `Result.points` is the provider's own
    championship points, stored for cross-validation and never scored from. The
    fantasy standings arrive in Phase 5. What this gives the styleguide is a
    real spread of real numbers next to real names.
    """
    stmt = (
        select(Result.driver_id, db.func.sum(Result.points).label("total"))
        .where(Result.season_id == season.id, Result.points.isnot(None))
        .group_by(Result.driver_id)
        .order_by(db.func.sum(Result.points).desc())
        .limit(limit)
    )
    rows = db.session.execute(stmt).all()
    if not rows:
        return []
    drivers = {
        d.id: d
        for d in db.session.scalars(
            select(Driver).where(Driver.id.in_([r[0] for r in rows]))
        )
    }
    return [(drivers[did], float(total)) for did, total in rows if did in drivers]


def fastest_lap_driver(results: list[Result]) -> Result | None:
    """The quickest lap of the race, by parsed `lap_time`.

    Never `fastest_lap_rank` — that is eligibility-restricted to the top ten
    and disagrees with the truth on eight of seventeen S12 rounds (SPEC.md §3).
    Included here so the styleguide marks the right row.
    """
    best: Result | None = None
    best_seconds: float | None = None
    for r in results:
        seconds = parse_lap_time(r.lap_time)
        if seconds is None:
            continue
        if best_seconds is None or seconds < best_seconds:
            best, best_seconds = r, seconds
    return best


def parse_lap_time(value: str | None) -> float | None:
    """`"1:10.945"` to seconds. String comparison happens to work on Formula E
    lap times only because every lap is a single-digit minute; parse anyway."""
    if not value:
        return None
    parts = value.split(":")
    try:
        seconds = float(parts[-1])
        for i, part in enumerate(reversed(parts[:-1]), start=1):
            seconds += float(part) * (60 ** i)
    except ValueError:
        return None
    return seconds
