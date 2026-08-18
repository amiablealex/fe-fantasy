"""League and league membership models.

Leagues are durable across seasons (SPEC.md §2): a League row carries no
`season_id`, and season scoping applies to the standings computed over it.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from flask import current_app
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

ROLE_MEMBER = "member"
ROLE_ADMIN = "admin"
ROLES = (ROLE_MEMBER, ROLE_ADMIN)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class League(db.Model):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)

    # Nullable with ON DELETE SET NULL, deliberately diverging from the F1 app
    # (SPEC.md §7). There the FK is NOT NULL and RESTRICT, so any user who has
    # created a league hits an unhandled IntegrityError when deleting their
    # account. Administration lives on the membership row instead, so a league
    # survives its creator leaving.
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    creator = relationship("User", back_populates="leagues_created", foreign_keys=[created_by_id])
    memberships = relationship(
        "LeagueMembership",
        back_populates="league",
        cascade="all, delete-orphan",
    )

    @staticmethod
    def generate_invite_code() -> str:
        alphabet = current_app.config["INVITE_CODE_ALPHABET"]
        length = current_app.config["INVITE_CODE_LENGTH"]
        return "".join(secrets.choice(alphabet) for _ in range(length))

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

    league = relationship("League", back_populates="memberships")
    user = relationship("User", back_populates="league_memberships")

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN
