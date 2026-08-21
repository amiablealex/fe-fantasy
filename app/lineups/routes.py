"""The lineup editor.

One route, deliberately. There is no meeting in the URL because there is no
choice of meeting: only the earliest unlocked weekend is editable (SPEC.md §2),
so a `/lineup/<sequence>` route would exist solely to reject five sequences out
of six.

**The draft lives in the query string.** `?d=4,9,12,17&t=3` is the whole editor
state, which means every constraint check and every transfer cost on screen
comes from `app/scoring/lineups.py` — the same module `service.commit`
enforces — rather than from a copy of the rules written in JavaScript that
drifts the first time a rule changes. The cost is a round trip per tap, which
HTMX makes invisible and which this app can afford at twenty drivers.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import select

from app import palette
from app.extensions import db
from app.lineups import draft, service
from app.models.calendar import Season
from app.scoring import lineups as rules

lineups_bp = Blueprint(
    "lineups", __name__, template_folder="../templates/lineups"
)


def current_season() -> Season | None:
    """The season in play: the latest one synced.

    Not a configured constant. Season 13 appears in the database when it is
    first synced, and the app should follow it there rather than needing a
    redeploy to notice.
    """
    return db.session.scalars(
        select(Season).order_by(Season.year.desc()).limit(1)
    ).first()


def now() -> datetime:
    """The clock, overridable in development only.

    Every deadline in the backfilled Season 12 is in the past, so without this
    the editor has nothing to open against the only real data that exists and
    could not be exercised until December. `FANTASY_NOW=2026-03-01T00:00:00Z`
    in `.env` puts the app mid-season. Ignored entirely outside debug, so it
    cannot leak into production behaviour.
    """
    # Not under test: the suite builds its own calendars against the real clock,
    # and a development override silently rewriting them would make every route
    # test a test of `.env`.
    if current_app.debug and not current_app.testing:
        override = os.environ.get("FANTASY_NOW")
        if override:
            try:
                return datetime.fromisoformat(
                    override.replace("Z", "+00:00")
                ).astimezone(timezone.utc)
            except ValueError:
                current_app.logger.warning("FANTASY_NOW is not a datetime: %r", override)
    return datetime.now(timezone.utc)


def _ids(raw: str | None) -> list:
    if not raw:
        return []
    out = []
    for part in raw.split(","):
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


def _draft_from_request(state) -> tuple[list, int | None]:
    """The draft on screen: the query string, or the stored lineup to start from.

    An explicit empty `d=` is a real draft — it is what "clear everything"
    produces — so absence of the parameter, not its emptiness, means "open with
    what I already have".
    """
    if "d" not in request.args:
        start = state.starting_draft
        if start:
            return sorted(start.drivers), start.team_id
        return [], None
    raw_team = request.args.get("t")
    return _ids(request.args.get("d")), (
        int(raw_team) if raw_team and raw_team.isdigit() else None
    )


@lineups_bp.route("/lineup")
@login_required
def edit():
    season = current_season()
    ctx = {"palette": palette, "season": season, "meeting": None}
    if season is None:
        return render_template("lineups/edit.html", **ctx)

    meeting = service.open_meeting(season, now())
    ctx["meeting"] = meeting
    if meeting is None:
        # Either the season has not been synced or every deadline has passed.
        # Both are the same thing to a player: nothing to pick for.
        return render_template("lineups/edit.html", **ctx)

    state = service.lineup_state(current_user, meeting, now=now())
    draft_drivers, draft_team = _draft_from_request(state)

    problems, cost, _ = draft.draft_status(
        state.roster, draft_drivers, draft_team, state.baseline
    )
    diff = draft.transfer_diff(
        state.roster, state.baseline, draft_drivers, draft_team
    )

    # An unaffordable draft is a broken rule like any other, and reads in the
    # same place and the same voice as one.
    if not state.budget.allows(diff.cost):
        problems = problems + [
            f"This costs {diff.cost} transfers and you have "
            f"{state.budget.available}. Put one of your original picks back."
        ]

    filled = len(draft_drivers) + (1 if draft_team is not None else 0)
    ctx.update(
        state=state,
        draft_drivers=draft_drivers,
        draft_team=draft_team,
        edit_drivers=[draft.slot_view(state.roster, d) for d in draft_drivers],
        edit_team=draft.team_slot_view(state.roster, draft_team),
        options=draft.picker_options(state.roster, draft_drivers, draft_team),
        problems=problems,
        diff=diff,
        cost=cost,
        filled=filled,
        complete=filled == rules.TOTAL_SLOTS,
        open_slot=request.args.get("open"),
        confirm=request.args.get("confirm") == "commit",
        mode="edit" if state.starting_draft else "empty",
    )
    return render_template("lineups/edit.html", **ctx)


@lineups_bp.route("/lineup", methods=["POST"])
@login_required
def commit():
    """Write the draft, revalidating every rule on the way in.

    The draft arrives as form fields rather than being re-read from the query
    string, so what is stored is what the confirmation showed. `service.commit`
    checks the lock, the roster and the budget again regardless — the client is
    convenience, never authority.
    """
    season = current_season()
    meeting = service.open_meeting(season, now()) if season else None
    if meeting is None:
        flash("There is no weekend open for picks.", "error")
        return redirect(url_for("lineups.edit"))

    raw_team = request.form.get("t", "")
    try:
        lineup = rules.Lineup.of(
            _ids(request.form.get("d")),
            int(raw_team) if raw_team.isdigit() else None,
        )
    except rules.LineupError:
        flash("Pick four drivers and a team before saving.", "error")
        return redirect(url_for("lineups.edit"))

    try:
        service.commit(current_user, meeting, lineup, now=now())
    except service.CommitRefused as refusal:
        for problem in refusal.problems:
            flash(problem, "error")
        return redirect(url_for("lineups.edit"))

    flash(f"Lineup saved for {meeting.display_name}.", "success")
    return redirect(url_for("lineups.edit"))
