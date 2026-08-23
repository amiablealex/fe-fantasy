"""The weekend view: what happened, and what it did for you.

Three routes and one page. `/weekend` is the first screen in this application
that answers a question about a meeting rather than about the player — a race
classification, a qualifying bracket, a driver's season — and until stage 7.2
none of it existed outside a blueprint registered only when `app.debug` is true.

**Why this is not the front page.** `/` is the state of play: when the next
weekend locks, what is left to spend, and where you stand. Every one of those is
something a player can still act on. This page is the opposite — a finished
weekend, in as much detail as they want. Putting both on one screen would make
the actionable half compete with the retrospective half, and during a race
weekend they are not even about the same meeting.

**A lineup appears here only once the weekend has locked.** Not a privacy rule
about yourself — you may read your own draft freely, on `/lineup`, which is
where editing lives. It is that a page showing an editable lineup outside the
editor is a second editor, and the two would drift. Before lock this page is the
schedule and a link.

The nav, results and profile partials were promoted out of `app/templates/
styleguide/` unchanged in shape, per SPEC.md §8's entry conditions — the same
path `_lineup.html` and `scoring_bridge` took into Phases 4 and 5.
"""

from __future__ import annotations

from flask import Blueprint, render_template, request, url_for
from flask_login import current_user, login_required

from app import palette
from app.clock import now
from app.lineups import draft, service
from app.lineups.routes import countdown
from app.lineups.service import current_season
from app.meetings import bracket, display, queries, view
from app.meetings.bridge import ruleset_for

meetings_bp = Blueprint(
    "meetings", __name__, template_folder="../templates/meetings"
)

STAGE_RACE = "race"
STAGE_QUALIFYING = "qualifying"


def default_sequence(refs, latest_scored, open_sequence) -> int | None:
    """Which weekend the page opens on when the URL does not say.

    The most recently scored one, because that is the weekend a player has a
    reason to look at: it is the one with a number against their name. Failing
    that the open weekend, which before the season starts is the opener and is
    the only thing there is to show. Failing both, the first in the calendar.

    Pure, and separated from the route so it can be tested without a database:
    it is the one piece of judgement on this page and it has four cases.
    """
    if latest_scored is not None:
        return latest_scored
    if open_sequence is not None:
        return open_sequence
    return refs[0].sequence if refs else None


def _subject(raw: str | None):
    """Parse a `d123` / `t7` profile parameter into (kind, id).

    Returns (None, None) for anything else. A profile parameter is
    reader-supplied and the two prefixes are the whole vocabulary, so an
    unrecognised one is not an error worth a page — it is a link someone
    truncated.
    """
    if not raw or len(raw) < 2 or not raw[1:].isdigit():
        return None, None
    if raw[0] not in ("d", "t"):
        return None, None
    return raw[0], int(raw[1:])


def _profile_for(season, raw: str | None):
    kind, subject_id = _subject(raw)
    if kind == "d":
        return queries.driver_profile(season, subject_id)
    if kind == "t":
        return queries.team_profile(season, subject_id)
    return None


def _chosen_round(meeting, requested: int | None):
    ordered = sorted(meeting.rounds, key=lambda r: r.round_number)
    if not ordered:
        return None, []
    shown = next(
        (r for r in ordered if r.round_number == requested), ordered[0]
    )
    return shown, ordered


def _results_context(meeting, sequence: int) -> dict:
    """Everything the Results disclosure needs, for the page and the fragment.

    One function, two callers. The disclosure body is rendered both inline and
    by the HTMX route so a round or stage switch swaps in place rather than
    reloading and throwing away the reader's scroll position — and building its
    context in two places is how the two start disagreeing about which round is
    shown.
    """
    shown, ordered = _chosen_round(meeting, request.args.get("r", type=int))
    if shown is None:
        return {}

    stage = request.args.get("stage", STAGE_RACE)
    if stage not in (STAGE_RACE, STAGE_QUALIFYING):
        stage = STAGE_RACE

    rules = ruleset_for(shown)
    results = queries.round_results(shown)
    base = url_for("meetings.weekend")
    return {
        "base": base,
        "sequence": sequence,
        "meeting_rounds": ordered,
        "shown_round": shown,
        "stage": stage,
        "results": results,
        # The FP column. `RoundScore` is user-independent, so this is one
        # read of thirty rows regardless of who is looking at the page.
        "scores": queries.round_scores(shown),
        # The bracket derives its per-stage figures from position plus the
        # round's own recorded ruleset, never from the current one — a re-tune
        # after Jeddah must not rewrite what December was worth.
        "bracket": bracket.build(results.qualifying, rules),
        "bracket_rules": rules.qualifying,
        "schedule": queries.round_schedule(shown),
        "profile_base": (
            f"{base}?m={sequence}&r={shown.round_number}"
            f"&stage={stage}&results=open"
        ),
        "profile_hx": url_for("meetings.weekend_profile"),
    }


@meetings_bp.route("/weekend")
@login_required
def weekend():
    moment = now()
    season = current_season()
    ctx = {
        "palette": palette,
        "bridge": display,
        "season": season,
        "meeting": None,
        "refs": [],
    }
    if season is None:
        return render_template("meetings/weekend.html", **ctx)

    refs = queries.meeting_refs(season)
    open_meeting = service.open_meeting(season, moment)
    sequence = request.args.get("m", type=int)
    if sequence is None:
        sequence = default_sequence(
            refs,
            queries.latest_scored(refs),
            open_meeting.sequence if open_meeting else None,
        )

    ctx.update(
        refs=refs,
        sequence=sequence,
        nav=queries.neighbours(refs, sequence) if sequence else None,
        menu=request.args.get("menu"),
    )
    if sequence is None:
        return render_template("meetings/weekend.html", **ctx)

    meeting = queries.get_meeting(season, sequence)
    ctx["meeting"] = meeting
    if meeting is None or not meeting.rounds:
        return render_template("meetings/weekend.html", **ctx)

    locked = meeting.is_locked(moment)
    ctx.update(
        locked=locked,
        countdown=countdown(meeting.deadline_at, moment),
        editable=(open_meeting is not None and open_meeting.id == meeting.id),
    )

    # The lineup, only once the weekend has locked. Before that this page is
    # the schedule; the editor is where an open weekend is answered.
    snapshot = service.effective_snapshot(current_user, meeting) if locked else None
    if snapshot is not None and snapshot.is_complete:
        lineup = snapshot.to_lineup()
        breakdowns = view.score_meeting(season, meeting, lineup)
        picks = view.aggregate_meeting(breakdowns)
        best = view.meeting_best_lineup(season, meeting)
        view.mark_best(picks, best.lineup)

        # A locked weekend that has not been scored still shows the five picks.
        # A page that renders nothing cannot tell "you had no lineup" apart from
        # "no results yet", and those are opposite things to a reader.
        if not picks:
            roster = service.meeting_roster(meeting)
            ctx.update(
                locked_drivers=[
                    draft.slot_view(roster, d) for d in sorted(lineup.drivers)
                ],
                locked_team=draft.team_slot_view(roster, lineup.team_id),
            )

        ctx.update(
            picks=picks,
            best=best,
            # Only scored rounds contribute. A double-header with one round in
            # shows the round that has landed, and `provisional` on the ref
            # says the figure is a partial sum rather than a final one.
            total=sum((b.total for b in breakdowns if b.scored), 0),
            committed=snapshot.meeting_id == meeting.id,
        )

    ctx.update(_results_context(meeting, sequence))
    ctx["results_open"] = request.args.get("results") == "open"

    # Profiles open over whatever is already on screen and close by dropping the
    # parameter, so closing one returns the reader to the row they tapped.
    ctx["profile"] = _profile_for(season, request.args.get("profile"))
    ctx["profile_close"] = request.url.split("&profile=")[0]

    return render_template("meetings/weekend.html", **ctx)


@meetings_bp.route("/weekend/results")
@login_required
def weekend_results():
    """The Results disclosure body, on its own, for HTMX to swap in place."""
    season = current_season()
    sequence = request.args.get("m", type=int)
    meeting = queries.get_meeting(season, sequence) if season and sequence else None
    if meeting is None or not meeting.rounds:
        return "", 204

    ctx = _results_context(meeting, sequence)
    if not ctx:
        return "", 204
    return render_template(
        "meetings/_results_body.html", palette=palette, bridge=display, **ctx
    )


@meetings_bp.route("/weekend/profile")
@login_required
def weekend_profile():
    """A driver or team profile sheet, for HTMX to drop into the page.

    Opening a profile as a full navigation reloads the weekend and throws away
    the reader's position — tapping a driver halfway down a classification sent
    them back to the top. The links keep their plain `href`, so this still works
    with JavaScript off; that path navigates, as it did before.
    """
    season = current_season()
    profile = _profile_for(season, request.args.get("subject")) if season else None
    if profile is None:
        return "", 204

    return render_template(
        "meetings/_profile_sheet.html",
        bridge=display,
        palette=palette,
        profile=profile,
        close_url=request.args.get("back") or url_for("meetings.weekend"),
    )
