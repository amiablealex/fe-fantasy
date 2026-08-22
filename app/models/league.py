"""League and league membership models.

Leagues are durable across seasons (SPEC.md §2): a League row carries no
`season_id`, and season scoping applies to the standings computed over it.

One league carries `is_global` and holds every user. It exists so the
co-membership half of the visibility rule can be relaxed by data rather than
by deleting a predicate — see `app/leagues/visibility.py`, which has one
clause and no special case for it.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from flask import current_app
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

ROLE_MEMBER = "member"
ROLE_ADMIN = "admin"
ROLES = (ROLE_MEMBER, ROLE_ADMIN)

# The global league's name and its sentinel invite code. `GLOBAL` contains O
# and L, neither of which is in INVITE_CODE_ALPHABET, so a generated code can
# never collide with it and the global league can never be reached by someone
# guessing codes.
GLOBAL_LEAGUE_NAME = "FE Fantasy"
GLOBAL_INVITE_CODE = "GLOBAL"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class League(db.Model):
    __tablename__ = "leagues"
    __table_args__ = (
        # At most one global league. Partial unique index rather than a check
        # constraint, because the rule is across rows rather than within one.
        Index(
            "uq_league_global",
            "is_global",
            unique=True,
            postgresql_where=text("is_global"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)

    # Nullable with ON DELETE SET NULL, deliberately diverging from the F1 app
    # (SPEC.md §7). There the FK is NOT NULL and RESTRICT, so any user who has
    # created a league hits an unhandled IntegrityError when deleting their
    # account. Administration lives on the membership row instead, so a league
    # survives its creator leaving.
    #
    # The global league has no creator, which is the case this nullability was
    # already the right shape for.
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # Everyone is a member. Not a flag the interface can set: a league is
    # global because the migration made it so, and there is exactly one.
    is_global: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    creator = relationship("User", back_populates="leagues_created", foreign_keys=[created_by_id])
    memberships = relationship(
        "LeagueMembership",
        back_populates="league",
        cascade="all, delete-orphan",
    )

    @staticmethod
    def generate_invite_code() -> str:
        """One candidate code. Collision handling belongs to the caller.

        A check-then-insert races, so the service generates in a loop and lets
        the unique constraint arbitrate rather than asking the database whether
        a code is free.
        """
        alphabet = current_app.config["INVITE_CODE_ALPHABET"]
        length = current_app.config["INVITE_CODE_LENGTH"]
        return "".join(secrets.choice(alphabet) for _ in range(length))

    @property
    def joinable(self) -> bool:
        """The global league is never joined by code — everyone is already in."""
        return not self.is_global

    def __repr__(self) -> str:  # pragma: no cover
        return f"<League {self.name!r} ({self.invite_code})>"


class LeagueMembership(db.Model):
    __tablename__ = "league_memberships"
    __table_args__ = (
        UniqueConstraint("league_id", "user_id", name="uq_league_membership"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), default=ROLE_MEMBER, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # Opt out of being shown, without leaving. Deliberately not a deleted row:
    # leaving takes the member's read access with it, and the account setting
    # this backs says "show me on the global league", not "show me the global
    # league".
    #
    # It is asymmetric on purpose. A hidden member still sees everyone else and
    # still sees their own locked lineups; only their visibility to others is
    # withdrawn. That is safe because every lineup reachable through
    # `app/leagues/visibility.py` is already past its deadline, so there is
    # nothing to be gained by lurking.
    #
    # The column is general, but only the global league's toggle sets it.
    # Hiding inside a private league would remove the thing the league is for.
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    league = relationship("League", back_populates="memberships")
    user = relationship("User", back_populates="league_memberships")

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LeagueMembership league={self.league_id} user={self.user_id} {self.role}>"
