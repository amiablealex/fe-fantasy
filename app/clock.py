"""The application clock.

One function, in its own module, because two blueprints need it and neither
owns it. It was written inside `app/lineups/routes.py` when the editor was the
only thing that had to know what day it was; the league table is the second
caller, and a helper imported from another blueprint's route module is the kind
of coupling that is easy to add and unpleasant to unpick later.

`FANTASY_NOW` moves the app's clock in development. Every deadline in the
backfilled Season 12 is in the past, so without it the editor and now the
standings have nothing to open against the only real data that exists, and
could not be exercised until December.

It is deliberately **not** gated on `app.debug`, which is set at different
points under `flask run`, gunicorn and a shell and therefore means different
things in each. It is gated on a loud warning instead: if this ever reaches
Railway it says so on every request that uses it.

It is excluded under test. The suite builds its calendars against the real
clock, and an override silently rewriting them would turn every route test
into a test of `.env`.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from flask import current_app


def now() -> datetime:
    override = None if current_app.testing else os.environ.get("FANTASY_NOW")
    if override:
        current_app.logger.warning("Clock overridden by FANTASY_NOW=%s", override)
        try:
            return datetime.fromisoformat(
                override.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except ValueError:
            current_app.logger.warning("FANTASY_NOW is not a datetime: %r", override)
    return datetime.now(timezone.utc)
