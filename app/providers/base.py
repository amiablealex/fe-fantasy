"""Provider protocol and the normalised shapes every provider must return.

The point of this module is that nothing downstream sees a vendor payload. The
Orange Cat Blacktop client does the coercion — string positions to ints, absent
keys to None, ISO strings to datetimes — and returns the objects below. A second
provider becomes a second module implementing the same protocol, rather than a
refactor of everything that touches results (SPEC.md §6, §12).

These are frozen dataclasses rather than dicts so a shape change is an
AttributeError at the call site instead of a silent None thirty lines later.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterator, Protocol, runtime_checkable

# Session type values observed in live payloads. `other` is real — Season 13
# adds a shakedown day, and Appendix A's claim of three values is wrong.
SESSION_TYPE_PRACTICE = "practice"
SESSION_TYPE_QUALIFYING = "qualifying"
SESSION_TYPE_RACE = "race"
SESSION_TYPE_OTHER = "other"

SESSION_STATUS_SCHEDULED = "scheduled"
SESSION_STATUS_ONGOING = "ongoing"
SESSION_STATUS_COMPLETED = "completed"


# -----------------------------------------------------------------------------
# Reference data
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class SeasonRef:
    """A season as it appears in the seasons index.

    `year` is the year the season *ends*, not the year it starts. Season 12 ran
    December 2025 to August 2026 and is keyed 2026; Season 13 runs December 2026
    to July 2027 and will be keyed 2027. Getting this backwards silently returns
    the wrong season, because the payload is perfectly valid either way.
    """

    id: str
    year: int
    status: str | None = None
    round_count: int | None = None


@dataclass(frozen=True)
class Country:
    name: str | None
    two_code: str | None
    three_code: str | None


@dataclass(frozen=True)
class Location:
    """`id` is stable across seasons, which is what makes multi-season location
    records and meeting derivation possible. `name` on the parent event is not —
    it carries the sponsor."""

    id: str
    name: str | None
    city: str | None
    country: Country | None


@dataclass(frozen=True)
class SessionSummary:
    id: str
    name: str
    type: str
    start_time: datetime | None
    end_time: datetime | None
    status: str | None

    @property
    def is_qualifying(self) -> bool:
        return self.type == SESSION_TYPE_QUALIFYING

    @property
    def is_race(self) -> bool:
        return self.type == SESSION_TYPE_RACE

    @property
    def is_complete(self) -> bool:
        return self.status == SESSION_STATUS_COMPLETED


@dataclass(frozen=True)
class EventSummary:
    """One race day. The API's top-level unit, and what SPEC.md §5 calls a Round.

    `sessions` is populated only from the events endpoint. The season detail
    endpoint returns the same events without them, which is why session times
    require a second call.
    """

    id: str
    name: str
    date_start: date | None
    date_end: date | None
    status: str | None
    location: Location | None
    sessions: tuple[SessionSummary, ...] = ()

    @property
    def qualifying_sessions(self) -> tuple[SessionSummary, ...]:
        return tuple(s for s in self.sessions if s.is_qualifying)

    @property
    def race_sessions(self) -> tuple[SessionSummary, ...]:
        return tuple(s for s in self.sessions if s.is_race)

    def earliest_qualifying_start(self) -> datetime | None:
        """Basis for the meeting deadline (SPEC.md §2)."""
        times = [s.start_time for s in self.qualifying_sessions if s.start_time]
        return min(times) if times else None


# -----------------------------------------------------------------------------
# Standings
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class TeamParticipation:
    """A driver's stint at one team, with the rounds they actually raced.

    `participation_rounds` is a list of round numbers, not a count, and it is
    per-team — so a mid-season switch is represented correctly. It grows during
    a season and is empty for a driver who has not yet raced, which is why it is
    display data for the picker and never roster truth (SPEC.md §6).
    """

    team_id: str
    name: str | None
    short_name: str | None
    color: str | None
    participation_rounds: tuple[int, ...] = ()

    @property
    def rounds_participated(self) -> int:
        return len(self.participation_rounds)


@dataclass(frozen=True)
class DriverStanding:
    id: str
    first_name: str | None
    last_name: str | None
    code: str | None
    number: int | None
    position: int | None
    points: Decimal | None
    teams: tuple[TeamParticipation, ...] = ()

    @property
    def rounds_participated(self) -> int:
        """Total across every team, for the driver picker."""
        return sum(t.rounds_participated for t in self.teams)

    @property
    def current_team(self) -> TeamParticipation | None:
        """The team of the most recent round raced.

        `teams` order is not guaranteed, so pick by highest round rather than
        by position in the list.
        """
        raced = [t for t in self.teams if t.participation_rounds]
        if not raced:
            return self.teams[0] if self.teams else None
        return max(raced, key=lambda t: max(t.participation_rounds))

    @property
    def display_name(self) -> str:
        """`code` is null for 16 of 20 drivers, so it can never be the primary
        label — it is decoration when present."""
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or f"#{self.number}" if self.number else self.id


@dataclass(frozen=True)
class TeamStanding:
    id: str
    name: str | None
    short_name: str | None
    color: str | None
    position: int | None
    points: Decimal | None


@dataclass(frozen=True)
class SeasonDetail:
    season: SeasonRef
    drivers: tuple[DriverStanding, ...] = ()
    teams: tuple[TeamStanding, ...] = ()
    schedule: tuple[EventSummary, ...] = ()

    @property
    def event_ids(self) -> frozenset[str]:
        """Used to filter the unfilterable events endpoint down to this season."""
        return frozenset(e.id for e in self.schedule)


# -----------------------------------------------------------------------------
# Results
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class DriverRef:
    id: str
    first_name: str | None
    last_name: str | None
    code: str | None
    number: int | None


@dataclass(frozen=True)
class TeamRef:
    id: str
    name: str | None
    short_name: str | None
    color: str | None


@dataclass(frozen=True)
class ResultRow:
    """One classification row.

    Field notes that cost real debugging time:

    - `position` arrives as a string, `grid_position` as an int. Both coerced.
    - `points` and `status` keys are ABSENT from qualifying rows, not null.
      `grid_position` is present-and-null there. Different failure modes.
    - `status` is None for classified finishers and "DNF" for retirements, but
      retirements still receive ranked positions — which is what makes places
      lost punish a DNF automatically, with no separate rule.
    - `lap_time` and `display_time` swap meaning by session type. In a race,
      `lap_time` is a lap and `display_time` the total. In a duel, `lap_time` is
      null and `display_time` carries the lap. Both are kept as raw strings;
      interpreting them is the caller's job, because only the caller knows the
      session type.
    - `display_time` has a variable shape: "1:01:13.217" for a race over an
      hour, "59:23.013" for one under. Never split on ":" expecting three parts;
      the 30-minute E-Prix Unleashed will be sub-hour every time.
    """

    id: str
    position: int | None
    grid_position: int | None
    driver: DriverRef | None
    team: TeamRef | None
    status: str | None
    points: Decimal | None
    fastest_lap_rank: int | None
    car_number: int | None
    lap_time: str | None
    display_time: str | None

    @property
    def is_retirement(self) -> bool:
        return self.status is not None

    @property
    def set_fastest_lap(self) -> bool:
        """The fantasy fastest-lap point derives from this, never from `points`.

        Formula E awards its championship fastest-lap point only to a top-ten
        finisher; this game does not apply that condition (SPEC.md §3).
        """
        return self.fastest_lap_rank == 1

    @property
    def has_grid_position(self) -> bool:
        """False for a pit-lane start or a data gap, where places gained/lost
        must score 0 rather than guess a grid slot."""
        return self.grid_position is not None and self.grid_position > 0


# -----------------------------------------------------------------------------
# Protocol
# -----------------------------------------------------------------------------


@runtime_checkable
class ResultsProvider(Protocol):
    """What the ingest layer is allowed to depend on."""

    def list_seasons(self) -> list[SeasonRef]:
        ...

    def resolve_season(self, ending_year: int) -> SeasonRef | None:
        """Find a season by its ending year, or None if not published yet.

        Not-yet-published is a normal condition, not an error: Season 13 does
        not appear in the index until the vendor adds it.
        """
        ...

    def get_season_detail(self, season_id: str) -> SeasonDetail:
        ...

    def iter_events(self, page_size: int = 50) -> Iterator[EventSummary]:
        ...

    def get_results(self, event_id: str, session_id: str) -> list[ResultRow]:
        ...
