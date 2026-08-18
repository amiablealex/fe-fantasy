"""SQLAlchemy models.

Every model module must be imported here. Alembic's autogenerate walks
SQLAlchemy's metadata, and a model that is never imported is invisible to it —
which produces a migration that silently drops the table.
"""
from __future__ import annotations

from app.models import league, user  # noqa: F401

__all__ = ["league", "user"]
