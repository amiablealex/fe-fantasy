"""Grid models: Driver, Team, SeatEntry.

Driver and Team are global rather than season-scoped, because the provider's
UUIDs persist across seasons — which is what makes a multi-season driver history
possible later without a migration.

The season-scoped part is SeatEntry: who drove for whom, in which rounds.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class Driver(db.Model):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_driver_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    first_name: Mapped[str | None] = mapped_column(String(80))
    last_name: Mapped[str | None] = mapped_column(String(80))
    # Null for 16 of 20 drivers. Decoration only — never a key, never the
    # primary label.
    code: Mapped[str | None] = mapped_column(String(8))
    number: Mapped[int | None] = mapped_column(Integer)

    seat_entries = relationship(
        "SeatEntry", back_populates="driver", cascade="all, delete-orphan"
    )

    @property
    def display_name(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        if parts:
            return " ".join(parts)
        return f"#{self.number}" if self.number else self.provider_driver_id

    @property
    def short_label(self) -> str:
        """For dense tables: surname, falling back to the car number."""
        if self.last_name:
            return self.last_name
        return f"#{self.number}" if self.number else self.provider_driver_id

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Driver {self.short_label}>"


class Team(db.Model):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_team_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(120))
    short_name: Mapped[str | None] = mapped_column(String(80))
    # Stored but not trusted: Andretti and Jaguar are both "000000". Not a
    # usable palette, and the design system does not read it.
    color: Mapped[str | None] = mapped_column(String(16))

    seat_entries = relationship(
        "SeatEntry", back_populates="team", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Team {self.short_name or self.name}>"


class SeatEntry(db.Model):
    """A driver's stint at one team within one season.

    More load-bearing than it looks. It is the driver picker's
    rounds-participated figure, but it is also the source of truth for the
    one-driver-per-team lineup constraint (SPEC.md §2) — and because a driver
    can switch teams mid-season, that constraint has to know which team they
    were on *at that meeting*. Disjoint round arrays give exactly that.

    `participation_rounds` comes straight from the provider's
    `driver.teams[].participationRounds`: an array of round numbers, not a
    count. It grows during a season and is empty for a driver who has not raced
    yet, so it is display and constraint data — never a statement about who is
    on the grid.
    """

    __tablename__ = "seat_entries"
    __table_args__ = (
        UniqueConstraint("season_id", "driver_id", "team_id", name="uq_seat_entry"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participation_rounds: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=list, nullable=False
    )

    season = relationship("Season", back_populates="seat_entries")
    driver = relationship("Driver", back_populates="seat_entries")
    team = relationship("Team", back_populates="seat_entries")

    @property
    def rounds_participated(self) -> int:
        return len(self.participation_rounds or [])

    def covers_round(self, round_number: int) -> bool:
        """Whether this seat was the driver's at a given round.

        The question the lineup constraint actually asks.
        """
        return round_number in (self.participation_rounds or [])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SeatEntry driver={self.driver_id} team={self.team_id}>"
