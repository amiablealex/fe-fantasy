"""Loading the backfilled season into plain dicts.

Raw SQL on purpose. Importing the models would drag in SQLAlchemy and Flask, and
the point of the simulation is that it runs against the data without either.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import psycopg
from dotenv import load_dotenv

load_dotenv()


def database_url() -> str:
    """The plain Postgres URL.

    `config.py` rewrites this onto the psycopg driver for SQLAlchemy's benefit;
    psycopg itself wants it unadorned.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set. Source .env or export it.")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@dataclass
class RoundData:
    round_number: int
    meeting_sequence: int
    meeting_name: str
    date: Any
    format: str
    qualifying_sessions: list[dict] = field(default_factory=list)
    race_rows: list[dict] = field(default_factory=list)

    @property
    def has_qualifying(self) -> bool:
        return bool(self.qualifying_sessions)

    @property
    def has_race(self) -> bool:
        return bool(self.race_rows)


@dataclass
class SeasonData:
    year: int
    display_name: str
    rounds: list[RoundData]
    drivers: dict[int, str]                     # driver id -> label
    teams: dict[int, str]                       # team id -> label
    seats: dict[int, list[tuple[int, int]]]     # round -> [(driver_id, team_id)]

    def meetings(self) -> dict[int, list[RoundData]]:
        out: dict[int, list[RoundData]] = {}
        for rnd in self.rounds:
            out.setdefault(rnd.meeting_sequence, []).append(rnd)
        return out

    def team_of_driver(self, round_number: int) -> dict[int, int]:
        return {d: t for d, t in self.seats.get(round_number, [])}

    def drivers_by_team(self, round_number: int) -> dict[int, tuple[int, ...]]:
        grouped: dict[int, list[int]] = {}
        for driver_id, team_id in self.seats.get(round_number, []):
            grouped.setdefault(team_id, []).append(driver_id)
        return {t: tuple(sorted(d)) for t, d in sorted(grouped.items())}

    def driver_label(self, driver_id: int) -> str:
        return self.drivers.get(driver_id, str(driver_id))

    def team_label(self, team_id: int) -> str:
        return self.teams.get(team_id, str(team_id))


_ROUNDS_SQL = """
SELECT r.round_number, m.sequence, m.display_name, r.date, r.format
FROM rounds r
JOIN meetings m ON m.id = r.meeting_id
JOIN seasons s ON s.id = r.season_id
WHERE s.year = %s
ORDER BY r.round_number
"""

_SESSIONS_SQL = """
SELECT r.round_number, ses.id, ses.stage, ses.stage_index, ses.ordinal
FROM sessions ses
JOIN rounds r ON r.id = ses.round_id
JOIN seasons s ON s.id = r.season_id
WHERE s.year = %s AND ses.stage = ANY(%s)
ORDER BY r.round_number, ses.ordinal
"""

_RESULTS_SQL = """
SELECT res.session_id, res.driver_id, res.position, res.grid_position,
       res.status, res.lap_time
FROM results res
JOIN sessions ses ON ses.id = res.session_id
JOIN rounds r ON r.id = ses.round_id
JOIN seasons s ON s.id = r.season_id
WHERE s.year = %s
ORDER BY res.position
"""

_DRIVERS_SQL = """
SELECT id, COALESCE(NULLIF(last_name, ''), CONCAT('#', number), id::text)
FROM drivers
"""

_TEAMS_SQL = "SELECT id, COALESCE(NULLIF(short_name, ''), name, id::text) FROM teams"

_SEATS_SQL = """
SELECT se.driver_id, se.team_id, se.participation_rounds
FROM seat_entries se
JOIN seasons s ON s.id = se.season_id
WHERE s.year = %s
"""

QUALIFYING_STAGES = ["group", "quarter_final", "semi_final", "final"]


def load_season(year: int) -> SeasonData:
    with psycopg.connect(database_url()) as conn, conn.cursor() as cur:
        cur.execute("SELECT year, display_name FROM seasons WHERE year = %s", (year,))
        row = cur.fetchone()
        if row is None:
            raise SystemExit(
                f"Season {year} is not in the database. Run sync-season and "
                "backfill-results first."
            )
        season_year, display_name = row

        cur.execute(_ROUNDS_SQL, (year,))
        rounds = {
            rn: RoundData(round_number=rn, meeting_sequence=seq, meeting_name=name,
                          date=date, format=fmt)
            for rn, seq, name, date, fmt in cur.fetchall()
        }

        cur.execute(_SESSIONS_SQL, (year, QUALIFYING_STAGES + ["race"]))
        sessions = cur.fetchall()

        cur.execute(_RESULTS_SQL, (year,))
        rows_by_session: dict[int, list[dict]] = {}
        for session_id, driver_id, position, grid, status, lap_time in cur.fetchall():
            rows_by_session.setdefault(session_id, []).append({
                "driver_id": driver_id,
                "position": position,
                "grid_position": grid,
                "status": status,
                "lap_time": lap_time,
            })

        for round_number, session_id, stage, stage_index, _ordinal in sessions:
            rnd = rounds.get(round_number)
            if rnd is None:
                continue
            rows = rows_by_session.get(session_id, [])
            if stage == "race":
                rnd.race_rows = rows
            else:
                rnd.qualifying_sessions.append({
                    "stage": stage, "stage_index": stage_index, "rows": rows,
                })

        cur.execute(_DRIVERS_SQL)
        drivers = {i: label for i, label in cur.fetchall()}
        cur.execute(_TEAMS_SQL)
        teams = {i: label for i, label in cur.fetchall()}

        cur.execute(_SEATS_SQL, (year,))
        seats: dict[int, list[tuple[int, int]]] = {}
        for driver_id, team_id, participation in cur.fetchall():
            for round_number in participation or []:
                seats.setdefault(round_number, []).append((driver_id, team_id))

    return SeasonData(
        year=season_year,
        display_name=display_name,
        rounds=[rounds[k] for k in sorted(rounds)],
        drivers=drivers,
        teams=teams,
        seats=seats,
    )
