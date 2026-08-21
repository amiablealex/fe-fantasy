"""Game models: LineupSnapshot, LineupPick.

SPEC.md §5, the most important architectural decision in the project: store a
**complete snapshot per (user, meeting)** and treat the transfer allowance as a
validation rule *between* consecutive snapshots rather than stored truth. A
lineup at meeting 8 is then a read, not a replay of meetings 1-7.

Snapshots are **sparse**: a row exists only where a user committed. The
effective lineup for meeting N is the latest snapshot at or before N, which is
one indexed query. The alternative — materialising a carried-forward row for
every user at every deadline — needs a job that writes rows for people who have
stopped playing, and buys nothing the ordering query does not already give.

The five picks are rows rather than five columns on the snapshot, for two
reasons. The four drivers are a set (`lineups.Lineup` holds a frozenset), so
columns would let a reordering read as four transfers. And Phase 5 hangs
`PickScore` off a pick.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, object_session, relationship

from app.extensions import db
from app.scoring import lineups as rules


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


PICK_DRIVER = "driver"
PICK_TEAM = "team"
PICK_KINDS = (PICK_DRIVER, PICK_TEAM)


class LineupSnapshot(db.Model):
    """One user's five picks for one meeting.

    `season_id` is denormalised off the meeting deliberately: it is immutable,
    and the app runs across seasons, so "this user's season" stays a
    single-table query rather than a join for every league table and profile.
    """

    __tablename__ = "lineup_snapshots"
    __table_args__ = (
        # One snapshot per user per meeting. Editing before the deadline
        # rewrites this row; there is no revision history, because nothing in
        # the game reads one.
        UniqueConstraint(
            "user_id", "meeting_id", name="uq_lineup_snapshot_user_meeting"
        ),
        # A user's season, for profiles and standings.
        Index("ix_lineup_snapshots_user_season", "user_id", "season_id"),
        # Everyone's lineup at one meeting — the league-table shape in Phase 6.
        # The unique constraint above leads on user_id and cannot serve it.
        Index("ix_lineup_snapshots_meeting_user", "meeting_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )

    # The count of changed slots against the previous snapshot, computed by
    # `lineups.transfer_cost` at commit and stored so the bank is a running sum
    # rather than a re-diff of the whole season.
    #
    # This is the raw diff, NOT "what was charged". A commit made during the
    # season-start grace can change all five slots and cost the player nothing;
    # whether a diff is charged depends on the grace boundary, which is a
    # function of the user and the calendar, not of this row. A test asserts
    # this column always equals a recomputation.
    transfer_cost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    committed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    user = relationship("User", back_populates="lineup_snapshots")
    meeting = relationship("Meeting")
    picks = relationship(
        "LineupPick",
        back_populates="snapshot",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ----- reading -----

    @property
    def driver_ids(self) -> list[int]:
        """Sorted, because the four slots are interchangeable.

        Any ordering here is presentation, never identity. The picker sorts by
        surname; nothing should read an order out of storage.
        """
        return sorted(p.driver_id for p in self.picks if p.kind == PICK_DRIVER)

    @property
    def team_id(self) -> int | None:
        return next((p.team_id for p in self.picks if p.kind == PICK_TEAM), None)

    @property
    def is_complete(self) -> bool:
        return (
            len(self.driver_ids) == rules.DRIVER_SLOTS and self.team_id is not None
        )

    def to_lineup(self) -> rules.Lineup:
        """The engine's shape. Raises `LineupError` on an incomplete snapshot.

        Loudly, on purpose: the service writes all five picks in one
        transaction, so a snapshot that cannot become a `Lineup` is corruption
        rather than a state to render around.
        """
        return rules.Lineup.of(self.driver_ids, self.team_id)

    @classmethod
    def build(cls, *, user_id, season_id, meeting_id, lineup: rules.Lineup,
              transfer_cost: int = 0) -> "LineupSnapshot":
        return cls(
            user_id=user_id,
            season_id=season_id,
            meeting_id=meeting_id,
            transfer_cost=transfer_cost,
            picks=(
                [LineupPick.for_driver(d) for d in sorted(lineup.drivers)]
                + [LineupPick.for_team(lineup.team_id)]
            ),
        )

    def replace_picks(self, lineup: rules.Lineup) -> None:
        """Rewrite the five picks in place, keeping the snapshot row.

        The clear-and-flush is load-bearing. Assigning a new list marks the old
        picks as orphans, but nothing orders their DELETEs before the new
        rows' INSERTs inside a single flush, so `uq_lineup_pick_driver` fires
        against rows that are already on their way out. Emptying the collection
        and flushing first makes the removal a separate statement.
        """
        session = object_session(self)
        if session is not None and self.picks:
            self.picks.clear()
            session.flush()
        self.picks = (
            [LineupPick.for_driver(d) for d in sorted(lineup.drivers)]
            + [LineupPick.for_team(lineup.team_id)]
        )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LineupSnapshot user={self.user_id} meeting={self.meeting_id}>"


class LineupPick(db.Model):
    """One filled slot: a driver or the team.

    Two nullable foreign keys under a check constraint rather than a
    polymorphic `subject_id` plus `kind`. Real referential integrity in both
    directions, and the joins stay readable — which matters because Phase 5
    joins these to results and Phase 6 joins them to league members.

    `ondelete="RESTRICT"` on both: drivers and teams are global and keyed on a
    provider UUID, so deleting one is a mistake and should be loud rather than
    silently shredding stored lineups.
    """

    __tablename__ = "lineup_picks"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'driver' AND driver_id IS NOT NULL AND team_id IS NULL)"
            " OR (kind = 'team' AND team_id IS NOT NULL AND driver_id IS NULL)",
            name="ck_lineup_pick_kind",
        ),
        # No driver twice in one lineup. `driver_id` is null on the team row and
        # Postgres permits repeated nulls in a unique constraint, so this does
        # not constrain the team pick.
        UniqueConstraint("snapshot_id", "driver_id", name="uq_lineup_pick_driver"),
        # Exactly one team pick per snapshot. Partial unique index — the same
        # pattern SyncConflict uses for unresolved rows.
        Index(
            "uq_lineup_pick_team",
            "snapshot_id",
            unique=True,
            postgresql_where=text("kind = 'team'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("lineup_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    driver_id: Mapped[int | None] = mapped_column(
        ForeignKey("drivers.id", ondelete="RESTRICT"), index=True
    )
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), index=True
    )

    snapshot = relationship("LineupSnapshot", back_populates="picks")
    driver = relationship("Driver")
    team = relationship("Team")

    @classmethod
    def for_driver(cls, driver_id: int) -> "LineupPick":
        return cls(kind=PICK_DRIVER, driver_id=driver_id)

    @classmethod
    def for_team(cls, team_id: int) -> "LineupPick":
        return cls(kind=PICK_TEAM, team_id=team_id)

    def __repr__(self) -> str:  # pragma: no cover
        subject = self.driver_id if self.kind == PICK_DRIVER else self.team_id
        return f"<LineupPick {self.kind}={subject}>"
