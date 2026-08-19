"""Result and SyncConflict.

Result is one classification row from one session. SyncConflict is the record of
something a resync refused to apply.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

RESULT_STATUS_DNF = "DNF"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Result(db.Model):
    """One driver's line in one session's classification.

    Deliberately references `driver` and `team` directly rather than a
    SeatEntry. Keying on the seat would create an ordering dependency: a reserve
    driver can appear in results before the next season-detail sync has created
    their seat entry, and the ingest would fail on a foreign key. Results must
    always be able to land.
    """

    __tablename__ = "results"
    __table_args__ = (
        UniqueConstraint("session_id", "driver_id", name="uq_result_session_driver"),
        Index("ix_result_season_driver", "season_id", "driver_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Denormalised from session -> round -> season so season-scoped queries do
    # not need two joins (SPEC.md §7: season_id on every season-scoped table).
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_result_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )

    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), index=True
    )

    # Arrives as a string in the payload; cast on ingest.
    position: Mapped[int | None] = mapped_column(Integer)
    # Arrives as an int, and is present-and-null on qualifying rows. Null or
    # zero in a race means no places gained/lost score — never guess a slot.
    grid_position: Mapped[int | None] = mapped_column(Integer)

    # Absent (not null) on qualifying rows. Null for a classified finisher,
    # "DNF" for a retirement — and retirements still carry ranked positions,
    # which is what makes places-lost punish a DNF with no separate rule.
    status: Mapped[str | None] = mapped_column(String(16))
    # Real Formula E championship points, stored for cross-validation only. The
    # fantasy score never reads this.
    points: Mapped[float | None] = mapped_column(Numeric(6, 2))

    # 1 on the setter, null for everyone else. The fantasy fastest-lap point
    # derives from this and never from `points`, because Formula E awards its
    # own FL point only to a top-ten finisher and this game does not.
    fastest_lap_rank: Mapped[int | None] = mapped_column(Integer)
    car_number: Mapped[int | None] = mapped_column(Integer)

    # Kept as raw strings: their meaning swaps by session type, and
    # display_time's shape varies between sub-hour and over-hour races.
    # Interpreting them is the caller's job.
    lap_time: Mapped[str | None] = mapped_column(String(24))
    display_time: Mapped[str | None] = mapped_column(String(24))

    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    session = relationship("Session", back_populates="results")
    driver = relationship("Driver")
    team = relationship("Team")

    @property
    def is_retirement(self) -> bool:
        return self.status is not None

    @property
    def set_fastest_lap(self) -> bool:
        return self.fastest_lap_rank == 1

    @property
    def has_grid_position(self) -> bool:
        return self.grid_position is not None and self.grid_position > 0

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Result P{self.position} driver={self.driver_id}>"


# -----------------------------------------------------------------------------
# Sync conflicts
# -----------------------------------------------------------------------------

CONFLICT_DEADLINE_WOULD_MOVE_EARLIER = "deadline_would_move_earlier"
CONFLICT_MEETING_REGROUPED = "meeting_regrouped"
CONFLICT_ROUND_DISAPPEARED = "round_disappeared"
CONFLICT_ROUND_RENUMBERED = "round_renumbered"
CONFLICT_UNEXPECTED_SESSION_SHAPE = "unexpected_session_shape"
CONFLICT_UNRECOGNISED_QUALIFYING_SESSION = "unrecognised_qualifying_session"

CONFLICT_KINDS = (
    CONFLICT_DEADLINE_WOULD_MOVE_EARLIER,
    CONFLICT_MEETING_REGROUPED,
    CONFLICT_ROUND_DISAPPEARED,
    CONFLICT_ROUND_RENUMBERED,
    CONFLICT_UNEXPECTED_SESSION_SHAPE,
    CONFLICT_UNRECOGNISED_QUALIFYING_SESSION,
)

CONFLICT_LABELS = {
    CONFLICT_DEADLINE_WOULD_MOVE_EARLIER: "Deadline would move earlier",
    CONFLICT_MEETING_REGROUPED: "Meeting groups differently than before",
    CONFLICT_ROUND_DISAPPEARED: "Round no longer in the calendar",
    CONFLICT_ROUND_RENUMBERED: "Round number would change",
    CONFLICT_UNEXPECTED_SESSION_SHAPE: "Session count does not match the expected bracket",
    CONFLICT_UNRECOGNISED_QUALIFYING_SESSION: "Unrecognised qualifying session name",
}


class SyncConflict(db.Model):
    """A change a resync refused to apply.

    The policy in SPEC.md §6: safe changes apply silently, unsafe ones roll back
    that meeting untouched and record a row here. The remaining meetings apply
    normally, so one oddity never blocks a whole sync.

    `fingerprint` is a hash of the conflict's identity, unique among unresolved
    rows. A sync running twice daily against an unresolved conflict bumps
    `occurrences` rather than inserting a duplicate — so the admin page reads
    "seen 14 times since Tuesday" instead of showing fourteen identical rows.
    """

    __tablename__ = "sync_conflicts"
    __table_args__ = (
        Index(
            "uq_sync_conflict_open",
            "fingerprint",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    meeting_id: Mapped[int | None] = mapped_column(
        ForeignKey("meetings.id", ondelete="SET NULL"), index=True
    )

    kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # What was proposed versus what is stored. Free-form on purpose: every
    # conflict kind carries different evidence, and the admin page renders it as
    # key-value pairs rather than parsing it.
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    occurrences: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolution_note: Mapped[str | None] = mapped_column(String(500))

    season = relationship("Season")
    meeting = relationship("Meeting")
    resolved_by = relationship("User")

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None

    @property
    def label(self) -> str:
        return CONFLICT_LABELS.get(self.kind, self.kind)

    def __repr__(self) -> str:  # pragma: no cover
        state = "open" if self.is_open else "resolved"
        return f"<SyncConflict {self.kind} ({state})>"
