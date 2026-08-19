"""Calendar models: Season, Location, Meeting, Round, Session.

The three-level hierarchy from SPEC.md §5:

    Meeting    e.g. London          13 per season   transfer and deadline unit
      Round    R16, R17             21 per season   scoring unit
        Session  groups/duels/race  ~11 per round   ingestion only

Meeting has no counterpart in the API — it is derived by grouping events on
location and date adjacency. Round corresponds to what the API calls an event.
The word "event" is deliberately absent from this module.

Vocabularies (`format`, `type`, `stage`, and the conflict kinds in result.py)
are plain strings validated in Python rather than Postgres ENUM types. Altering
an enum is a migration with real teeth; adding a value to a tuple is not, and
these vocabularies are still settling — Formula E introduced a second race
format for Season 13 and could introduce a third.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

# The first Formula E season ended in 2015, so the ending year maps to a season
# number by subtracting this. Used only to seed an editable display name — the
# API has no season number, and nothing keys off this arithmetic.
_SEASON_NUMBER_EPOCH = 2014


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def season_number_for_year(ending_year: int) -> int:
    """Season 12 ended in 2026; Season 13 ends in 2027."""
    return ending_year - _SEASON_NUMBER_EPOCH


def default_season_display_name(ending_year: int) -> str:
    return f"Season {season_number_for_year(ending_year)}"


# -----------------------------------------------------------------------------
# Vocabularies
# -----------------------------------------------------------------------------

ROUND_FORMAT_EPRIX = "eprix"
ROUND_FORMAT_EPRIX_UNLEASHED = "eprix_unleashed"
ROUND_FORMATS = (ROUND_FORMAT_EPRIX, ROUND_FORMAT_EPRIX_UNLEASHED)

ROUND_FORMAT_LABELS = {
    ROUND_FORMAT_EPRIX: "E-Prix",
    ROUND_FORMAT_EPRIX_UNLEASHED: "E-Prix Unleashed",
}

# Mirrors the provider's session.type. Four values, not three — `other` is real,
# and Season 13's shakedown day will most likely arrive as one.
SESSION_TYPE_PRACTICE = "practice"
SESSION_TYPE_QUALIFYING = "qualifying"
SESSION_TYPE_RACE = "race"
SESSION_TYPE_OTHER = "other"
SESSION_TYPES = (
    SESSION_TYPE_PRACTICE,
    SESSION_TYPE_QUALIFYING,
    SESSION_TYPE_RACE,
    SESSION_TYPE_OTHER,
)

# Derived bracket position, resolved once at ingest from session.name so the
# scoring engine never re-parses a name. `stage_index` carries which one: groups
# are 1-2, quarter-finals 1-4, semi-finals 1-2, everything else null.
#
# Splitting stage from index rather than encoding "GROUP_A" as one value means
# the pre-2022 four-group format, or any future reshaping of the bracket, needs
# no schema change.
STAGE_PRACTICE = "practice"
STAGE_GROUP = "group"
STAGE_QUARTER_FINAL = "quarter_final"
STAGE_SEMI_FINAL = "semi_final"
STAGE_FINAL = "final"
STAGE_RACE = "race"
STAGE_OTHER = "other"
SESSION_STAGES = (
    STAGE_PRACTICE,
    STAGE_GROUP,
    STAGE_QUARTER_FINAL,
    STAGE_SEMI_FINAL,
    STAGE_FINAL,
    STAGE_RACE,
    STAGE_OTHER,
)

# Stages that award fantasy qualifying points (SPEC.md §3).
SCORING_QUALIFYING_STAGES = (
    STAGE_GROUP,
    STAGE_QUARTER_FINAL,
    STAGE_SEMI_FINAL,
    STAGE_FINAL,
)

SESSION_STATUS_SCHEDULED = "scheduled"
SESSION_STATUS_ONGOING = "ongoing"
SESSION_STATUS_COMPLETED = "completed"

ROUND_STATUS_SCHEDULED = "scheduled"
ROUND_STATUS_COMPLETED = "completed"


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------


class Season(db.Model):
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_season_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    # The year the season ENDS. Season 12 ran Dec 2025 to Aug 2026 and is 2026.
    # Reading this as the starting year silently selects the wrong season.
    year: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(32), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    meetings = relationship(
        "Meeting", back_populates="season", cascade="all, delete-orphan",
        order_by="Meeting.sequence",
    )
    rounds = relationship(
        "Round", back_populates="season", cascade="all, delete-orphan",
        order_by="Round.round_number",
    )
    seat_entries = relationship(
        "SeatEntry", back_populates="season", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Season {self.display_name} ({self.year})>"


class Location(db.Model):
    """A venue, independent of season.

    `provider_location_id` is stable across seasons, which is what makes "every
    London race" a query rather than a string match — and why meeting derivation
    groups on this rather than on the sponsor-polluted event name.
    """

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_location_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(80))
    country_name: Mapped[str | None] = mapped_column(String(80))
    country_two_code: Mapped[str | None] = mapped_column(String(2))
    country_three_code: Mapped[str | None] = mapped_column(String(3))

    meetings = relationship("Meeting", back_populates="location")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Location {self.city or self.name}>"


class Meeting(db.Model):
    """A race weekend. Derived, not provided.

    "Weekend" in the UI, `Meeting` here. One or two rounds; the transfer and
    deadline unit.
    """

    __tablename__ = "meetings"
    __table_args__ = (
        UniqueConstraint("season_id", "sequence", name="uq_meeting_season_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    # Clean name for display ("London"), kept apart from the provider's
    # "2026 Hankook London E-Prix".
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)

    # Computed at sync from the earliest qualifying session of the first round,
    # then persisted — never derived at request time, because schedules move.
    # Monotonic once published: a resync may push it later, never earlier.
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Provenance, so the UI can say "locks at Qual Group A, 14:00" rather than
    # showing a bare timestamp nobody can sanity-check.
    deadline_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL", use_alter=True,
                   name="fk_meetings_deadline_session"),
        nullable=True,
    )

    # Set by an admin confirming a derivation. A resync will not regroup a
    # locked meeting; it raises a sync conflict instead.
    grouping_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    season = relationship("Season", back_populates="meetings")
    location = relationship("Location", back_populates="meetings")
    rounds = relationship(
        "Round", back_populates="meeting", cascade="all, delete-orphan",
        order_by="Round.round_number",
    )
    deadline_session = relationship("Session", foreign_keys=[deadline_session_id])

    @property
    def is_double_header(self) -> bool:
        return len(self.rounds) > 1

    def is_locked(self, now: datetime | None = None) -> bool:
        """No deadline yet means not locked — an unsynced meeting is editable."""
        if self.deadline_at is None:
            return False
        return (now or _utcnow()) >= self.deadline_at

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Meeting {self.sequence}. {self.display_name}>"


class Round(db.Model):
    """One race and its supporting sessions. The scoring unit.

    Corresponds to a provider event. `round_number` is Formula E's own numbering
    — and is NOT in the payload: it is inferred from position in the season
    schedule, which is also what `participationRounds` refers to. Once assigned
    it is immutable; a resync that would renumber an existing round raises a
    sync conflict rather than updating.
    """

    __tablename__ = "rounds"
    __table_args__ = (
        UniqueConstraint("season_id", "round_number", name="uq_round_season_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_event_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )

    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    number_in_meeting: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    format: Mapped[str] = mapped_column(
        String(24), default=ROUND_FORMAT_EPRIX, nullable=False
    )
    # Admin override, same pattern as meeting grouping: the regulations say
    # double-headers "typically" carry one of each format, and typically is not
    # always.
    format_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Sponsor-polluted; retained for debugging a derivation, never displayed.
    provider_name: Mapped[str | None] = mapped_column(String(200))
    date: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[str | None] = mapped_column(String(16))

    # The ruleset in force when this round was created. Changing point values
    # must never retroactively rewrite a completed round (SPEC.md §3).
    scoring_ruleset_version: Mapped[str] = mapped_column(String(32), nullable=False)

    season = relationship("Season", back_populates="rounds")
    meeting = relationship("Meeting", back_populates="rounds")
    sessions = relationship(
        "Session", back_populates="round", cascade="all, delete-orphan",
        order_by="Session.ordinal",
    )

    @property
    def format_label(self) -> str:
        return ROUND_FORMAT_LABELS.get(self.format, self.format)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Round R{self.round_number} {self.format}>"


class Session(db.Model):
    """One session within a round. Ingestion only — never shown as itself.

    All nine qualifying sessions share `type = "qualifying"`, so the bracket
    position lives in `stage` plus `stage_index`, derived from the name at
    ingest. An unrecognised *qualifying* name must fail loudly, because a silent
    skip would corrupt scoring with no visible error.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(
        ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_session_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    stage_index: Mapped[int | None] = mapped_column(Integer)
    # Position within the round's schedule, preserving provider order.
    ordinal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Note the naming: sessions use startTime/endTime while the parent event
    # uses dateStart/dateEnd. Reading the event's names here yields a null
    # deadline.
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str | None] = mapped_column(String(16))

    # Set when results land. The poller checks provider status first, but this
    # is what makes re-ingestion idempotent and cheap to skip.
    results_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    round = relationship("Round", back_populates="sessions", foreign_keys=[round_id])
    results = relationship(
        "Result", back_populates="session", cascade="all, delete-orphan"
    )

    @property
    def is_scoring_qualifying(self) -> bool:
        return self.stage in SCORING_QUALIFYING_STAGES

    @property
    def is_race(self) -> bool:
        return self.stage == STAGE_RACE

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Session {self.name!r} ({self.stage})>"
