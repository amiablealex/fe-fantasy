"""Stored scores: RoundScore and PickScore.

SPEC.md §5 asked for points stored per `(user, meeting, round, pick)` with the
rule breakdown. Phase 5 splits that in two, because the breakdown is not a
per-user fact.

**`RoundScore` is the truth, and it is user-independent.** One row per
`(round, subject)`, where a subject is a driver or a team: thirty rows a round
at the current grid, whether the league has three players or three hundred.
"Cassidy, round 7, reached the Duels and finished P4" is the same sentence for
everyone who picked him, so it is written once. It carries the breakdown, the
ruleset version it was scored under, and nothing about any player.

**`PickScore` is the projection onto players.** It carries a number and
pointers — to the snapshot that was effective, and to the `RoundScore` the
number came from. It exists so a league table in Phase 6 is one `GROUP BY`
rather than a lateral join against sparse snapshots, and so "which lineup
earned this" is stored fact rather than a re-derivation months later.

The property that makes the per-user materialisation safe: a snapshot can only
be committed for the *open* meeting (§2), so a lineup can never change after
its rounds have been scored. Nothing a player does invalidates a `PickScore`.
Only a rescore does, and a rescore rewrites both tables together.

Both tables are rewritten wholesale per round rather than upserted. Scoring is
a pure function of the ingested results and the recorded ruleset, so
delete-and-rewrite inside one transaction is the cheapest way to be certain a
rerun cannot leave a stale row behind — including rows for a driver who has
since disappeared from the classification.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.scoring.engine import ScoreComponent

# Mirrors PICK_DRIVER / PICK_TEAM in models/lineup.py. The two vocabularies are
# the same words for the same distinction and a pick's kind is copied straight
# onto its score, so they must not drift.
SUBJECT_DRIVER = "driver"
SUBJECT_TEAM = "team"
SUBJECT_KINDS = (SUBJECT_DRIVER, SUBJECT_TEAM)

# Which half of the weekend a component came from. Stored rather than derived
# from the rule name: the aggregation code used to recover it by testing rule
# membership against a hard-coded qualifying tuple, which silently
# misclassifies the first rule anyone adds.
CONTEST_QUALIFYING = "qualifying"
CONTEST_RACE = "race"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _component_json(component: ScoreComponent, contest: str) -> dict:
    """One fired rule, as stored.

    `points` is a string, not a JSON number. Decimal is the whole point of the
    team half-sum — 5.5 has to survive — and Python's json module renders a
    Decimal through float, which is exactly the lossy path §3 forbids for
    rounding. A string round-trips exactly.
    """
    return {
        "rule": component.rule,
        "points": str(component.points),
        "detail": component.detail,
        "contest": contest,
    }


def breakdown_from(
    qualifying: Iterable[ScoreComponent], race: Iterable[ScoreComponent]
) -> list[dict]:
    """Serialise a `DriverRoundScore`'s two component tuples for storage."""
    return (
        [_component_json(c, CONTEST_QUALIFYING) for c in qualifying]
        + [_component_json(c, CONTEST_RACE) for c in race]
    )


class RoundScore(db.Model):
    """What one driver or one team scored in one round.

    Written by the scoring pass, read by everything: the profiles, the results
    pages, the Perfect Five brute force, and `PickScore`. Thirty rows a round
    turns the brute force into a read of thirty rows plus arithmetic, with no
    engine run behind it — which is why the Perfect Five stays computed rather
    than stored.
    """

    __tablename__ = "round_scores"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'driver' AND driver_id IS NOT NULL AND team_id IS NULL)"
            " OR (kind = 'team' AND team_id IS NOT NULL AND driver_id IS NULL)",
            name="ck_round_score_kind",
        ),
        # One score per driver per round, and one per team per round. Postgres
        # permits repeated nulls in a unique constraint, so each of these
        # constrains only the rows of its own kind and the two coexist without
        # a partial index.
        UniqueConstraint("round_id", "driver_id", name="uq_round_score_driver"),
        UniqueConstraint("round_id", "team_id", name="uq_round_score_team"),
        # A driver's or team's season, for the profile tables.
        Index("ix_round_scores_season_driver", "season_id", "driver_id"),
        Index("ix_round_scores_season_team", "season_id", "team_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_id: Mapped[int] = mapped_column(
        ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    driver_id: Mapped[int | None] = mapped_column(
        ForeignKey("drivers.id", ondelete="RESTRICT")
    )
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT")
    )

    # Numeric, not float. A team scores half the sum of its two cars, so halves
    # are real and are never rounded (SPEC.md §3).
    points: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)

    # The rules that fired, in the order the engine emitted them. Empty for a
    # team, whose score is an arithmetic consequence of its drivers' rather
    # than a set of rules in its own right.
    breakdown: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    # Free-form, same pattern as SyncConflict.detail. Teams carry
    # {"cars": [[driver_id, "9"], ...]} so the half-sum explains itself without
    # the reader needing the roster; drivers carry nothing.
    detail: Mapped[dict | None] = mapped_column(JSONB)

    # Denormalised from the round. A score must say how it was reached without
    # a join, because the whole point of versioning is that the round's version
    # and the current version are allowed to differ.
    ruleset_version: Mapped[str] = mapped_column(String(32), nullable=False)

    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    season = relationship("Season")
    round = relationship("Round")
    driver = relationship("Driver")
    team = relationship("Team")

    # ----- reading -----

    @property
    def subject_id(self) -> Any:
        return self.driver_id if self.kind == SUBJECT_DRIVER else self.team_id

    def components(self, contest: str | None = None) -> tuple[ScoreComponent, ...]:
        """The breakdown, back in the engine's own shape.

        Returning `ScoreComponent` rather than dicts is what lets the display
        code read a stored score and a freshly computed one through the same
        code path — which is the only reason Phase 5 can turn the profiles into
        a read without touching a template.
        """
        return tuple(
            ScoreComponent(
                rule=c["rule"],
                points=Decimal(c["points"]),
                detail=c.get("detail"),
            )
            for c in (self.breakdown or [])
            if contest is None or c.get("contest") == contest
        )

    @property
    def qualifying_components(self) -> tuple[ScoreComponent, ...]:
        return self.components(CONTEST_QUALIFYING)

    @property
    def race_components(self) -> tuple[ScoreComponent, ...]:
        return self.components(CONTEST_RACE)

    @property
    def cars(self) -> list[tuple[int, Decimal]]:
        """A team's two drivers and what each scored this round."""
        return [
            (int(driver_id), Decimal(points))
            for driver_id, points in ((self.detail or {}).get("cars") or [])
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RoundScore {self.kind}={self.subject_id} round={self.round_id} {self.points}>"


class PickScore(db.Model):
    """What one of a player's five slots scored in one round.

    A double-header writes two of these per slot against the same snapshot:
    the meeting is the transfer unit, the round is the scoring unit, and this
    is where those two facts meet.
    """

    __tablename__ = "pick_scores"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'driver' AND driver_id IS NOT NULL AND team_id IS NULL)"
            " OR (kind = 'team' AND team_id IS NOT NULL AND driver_id IS NULL)",
            name="ck_pick_score_kind",
        ),
        UniqueConstraint(
            "user_id", "round_id", "driver_id", name="uq_pick_score_driver"
        ),
        UniqueConstraint("user_id", "round_id", "team_id", name="uq_pick_score_team"),
        # A player's season total, in one table with no join (SPEC.md §7).
        Index("ix_pick_scores_user_season", "user_id", "season_id"),
        # Everyone's score at one meeting — the league-table shape in Phase 6.
        Index("ix_pick_scores_meeting_user", "meeting_id", "user_id"),
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
    round_id: Mapped[int] = mapped_column(
        ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # The snapshot that was *effective* at this meeting, which is often not one
    # committed for it — snapshots are sparse, so a player who last picked at
    # meeting 3 scores meeting 7 on meeting 3's lineup. Storing which row
    # earned the points means a season history never has to re-run the
    # at-or-before query to explain itself.
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("lineup_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # CASCADE, not SET NULL: a rescore deletes the round's RoundScore rows and
    # these must go with them. A PickScore whose RoundScore is gone is a number
    # with no derivation, which is worse than no row.
    round_score_id: Mapped[int] = mapped_column(
        ForeignKey("round_scores.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    driver_id: Mapped[int | None] = mapped_column(
        ForeignKey("drivers.id", ondelete="RESTRICT")
    )
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT")
    )

    # Copied from the RoundScore rather than joined for it. It is the column
    # every league table and season total sums, and a denormalised number that
    # is rewritten in the same transaction as its source cannot drift.
    points: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)

    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    user = relationship("User")
    season = relationship("Season")
    meeting = relationship("Meeting")
    round = relationship("Round")
    snapshot = relationship("LineupSnapshot")
    round_score = relationship("RoundScore")
    driver = relationship("Driver")
    team = relationship("Team")

    @property
    def subject_id(self) -> Any:
        return self.driver_id if self.kind == SUBJECT_DRIVER else self.team_id

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<PickScore user={self.user_id} round={self.round_id} "
            f"{self.kind}={self.subject_id} {self.points}>"
        )
