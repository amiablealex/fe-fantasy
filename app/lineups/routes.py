"""The lineup editor, and the state of play.

Two routes. `/` is what a player sees on opening the app: the weekend that is
live, when the next one locks, and what they have left to spend. `/lineup` is
the editor for the weekend that is open.

There is no meeting in either URL because there is no choice of meeting: only
the earliest unlocked weekend is editable (SPEC.md §2), so a
`/lineup/<sequence>` route would exist solely to reject five sequences out of
six.

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
    in `.env` puts the app mid-season.

    Not gated on `app.debug`: that is set at different points depending on the
    entry point, so it means different things under `flask run`, gunicorn and a
    shell. Gated on a loud warning instead — if this ever reaches Railway it
    says so on every request.

    Excluded under test: the suite builds its own calendars against the real
    clock, and an override silently rewriting them would make every route test
    a test of `.env`.
    """
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


def countdown(target: datetime | None, moment: datetime) -> str:
    """How long until a deadline, in the largest unit that is still honest.

    Days until the last day, then hours, then minutes. A player three weeks out
    does not want to read 504 hours, and a player twenty minutes out must not
    read "today".
    """
    if target is None:
        return "TBC"
    remaining = target - moment
    seconds = int(remaining.total_seconds())
    if seconds <= 0:
        return "Locked"
    if seconds >= 172800:
        return f"{seconds // 86400} days"
    if seconds >= 7200:
        return f"{seconds // 3600} hours"
    if seconds >= 120:
        return f"{seconds // 60} min"
    return "Seconds"


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


def _slots(roster, lineup):
    """A lineup as the component's five slots, or empty."""
    if lineup is None:
        return [], None
    return (
        [draft.slot_view(roster, d) for d in sorted(lineup.drivers)],
        draft.team_slot_view(roster, lineup.team_id),
    )


@lineups_bp.route("/")
def home():
    """The state of play.

    The lineup shown is the one that is **live**, not the one that is editable.
    During a race weekend those differ: your Jeddah picks are locked and being
    scored while the Mexico City editor is already open, and showing next
    weekend's draft on the front page while this weekend is running would be
    answering a question nobody asked.
    """
    ctx = {"palette": palette, "season": None, "open_meeting": None}
    if not current_user.is_authenticated:
        return render_template("lineups/home.html", **ctx)

    season = current_season()
    ctx["season"] = season
    if season is None:
        return render_template("lineups/home.html", **ctx)

    moment = now()
    open_meeting = service.open_meeting(season, moment)
    ctx["open_meeting"] = open_meeting
    if open_meeting is None:
        return render_template("lineups/home.html", **ctx)

    state = service.lineup_state(current_user, open_meeting, now=moment)
    locked = service.latest_locked_meeting(season, moment)

    if locked is not None:
        shown_meeting = locked
        shown_snapshot = service.effective_snapshot(current_user, locked)
        shown_roster = service.meeting_roster(locked)
    else:
        shown_meeting = open_meeting
        shown_snapshot = state.snapshot or state.previous
        shown_roster = state.roster

    drivers, team = _slots(
        shown_roster, shown_snapshot.to_lineup() if shown_snapshot else None
    )

    ctx.update(
        state=state,
        shown_meeting=shown_meeting,
        shown_locked=locked is not None,
        shown_drivers=drivers,
        shown_team=team,
        countdown=countdown(open_meeting.deadline_at, moment),
        # Nothing committed for the open weekend, but something carried into
        # it: the condition SPEC.md §7 asks to be visible on first load.
        unchanged=state.snapshot is None and state.previous is not None,
        carried_from=state.previous.meeting if state.previous else None,
    )
    return render_template("lineups/home.html", **ctx)


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
        countdown=countdown(meeting.deadline_at, now()),
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
    return redirect(url_for("lineups.home"))
