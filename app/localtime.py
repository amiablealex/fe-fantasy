"""Rendering a stored instant in the timezone the readers live in.

Every datetime in this database is UTC, which is right for storage and wrong for
a page. Season 13 runs 18 December to 25 July, so half the calendar falls inside
British Summer Time: a session at 14:00 UTC in Berlin is 15:00 to every player,
and a deadline shown an hour early is the kind of bug that costs someone a
lineup rather than merely looking untidy.

**One timezone for the whole installation, not one per user.** Every player is
in the UK. A per-user column would be a migration, a settings form and a
preference nobody would ever change, to solve a problem that does not exist. The
config value is the escape hatch if that stops being true, and it is one line.

The zone name is never assumed by the reader: `%Z` renders GMT or BST from the
zone itself, so nobody has to remember which side of the clock change a date
falls on and nothing needs updating twice a year.

`zoneinfo` is standard library on 3.11, so this adds no dependency.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app

DEFAULT_DISPLAY_TIMEZONE = "Europe/London"

# A datetime with a date, a time and the zone spelt out. `%-d` drops the leading
# zero, which matters at --step-2 where "Sat 06 Dec" reads as a code.
FORMAT_FULL = "%a %-d %b, %H:%M %Z"
# Inside a table, where the column heading already says what the figure is.
FORMAT_SHORT = "%a %-d %b \u00b7 %H:%M"
FORMAT_TIME = "%H:%M %Z"


def display_zone() -> ZoneInfo:
    """The configured zone, falling back rather than failing.

    A mistyped `DISPLAY_TIMEZONE` should not take the site down over a date
    format, so an unknown name logs and degrades to UTC — visibly wrong on the
    page, which is the point, rather than a 500 that hides which variable caused
    it.
    """
    name = DEFAULT_DISPLAY_TIMEZONE
    if current_app:
        name = current_app.config.get(
            "DISPLAY_TIMEZONE", DEFAULT_DISPLAY_TIMEZONE
        )
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        if current_app:
            current_app.logger.warning(
                "DISPLAY_TIMEZONE %r is not a known zone; falling back to UTC",
                name,
            )
        return ZoneInfo("UTC")


def to_display(value: datetime | None) -> datetime | None:
    """Move an instant into the display zone.

    A naive datetime is read as UTC. Every column in this schema is
    `DateTime(timezone=True)` so this should not arise, but a value that has
    been through a round trip somewhere careless would otherwise be shifted by
    an hour with no error — which is exactly the failure this module exists to
    prevent.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(display_zone())


def local(value: datetime | None, fmt: str = FORMAT_FULL) -> str:
    """Jinja filter: `{{ meeting.deadline_at | local }}`."""
    moved = to_display(value)
    if moved is None:
        return "—"
    return moved.strftime(fmt)


def local_short(value: datetime | None) -> str:
    """Jinja filter for a table cell, where the zone is stated once elsewhere."""
    return local(value, FORMAT_SHORT)


def zone_label(moment: datetime | None = None) -> str:
    """"GMT" or "BST", for the one place a table says it rather than repeating
    it in every row."""
    moved = to_display(moment or datetime.now(timezone.utc))
    return moved.strftime("%Z")


def register(app) -> None:
    app.jinja_env.filters["local"] = local
    app.jinja_env.filters["local_short"] = local_short
    app.jinja_env.globals["zone_label"] = zone_label
