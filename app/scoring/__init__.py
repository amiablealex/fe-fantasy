"""Scoring.

This package imports nothing from Flask or SQLAlchemy. It takes plain result
dicts and returns points, which is what lets `sim/` exercise it against the
backfilled Season 12 data without a web application or a database (SPEC.md §12).
Keep it that way.
"""
