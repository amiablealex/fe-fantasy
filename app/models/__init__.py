"""SQLAlchemy models.

Every model module must be imported here. Alembic's autogenerate walks
SQLAlchemy's metadata, and a model that is never imported is invisible to it —
which produces a migration that silently drops the table.
"""
from __future__ import annotations

from app.models import (  # noqa: F401
    calendar,
    grid,
    league,
    lineup,
    result,
    score,
    user,
    worker,
)

__all__ = [
    "calendar",
    "grid",
    "league",
    "lineup",
    "result",
    "score",
    "user",
    "worker",
]
