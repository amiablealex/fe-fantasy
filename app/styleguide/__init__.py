"""Development-only design surface.

Registered by the app factory only when `app.debug` is true.

    /styleguide            tokens and primitives
    /styleguide/lineup     the lineup component in all three states
    /styleguide/meeting    full round results, with the user's picks marked

The lineup page holds its draft **in the query string** rather than in
JavaScript. That is not a shortcut: it means the constraint check and the
transfer cost are computed by `app/scoring/lineups.py` — the real rules, the
same ones the server enforces on commit — rather than by a mirrored copy in
JavaScript that can drift out of step with them. Phase 4 replaces the full
reload with an HTMX partial and keeps everything else.
"""

from flask import Blueprint, render_template, request

from app import palette
from app.styleguide import queries, scoring_bridge

bp = Blueprint(
    "styleguide",
    __name__,
    url_prefix="/styleguide",
    template_folder="../templates/styleguide",
)

DEFAULT_ROUND = 1
# Berlin: a double-header, so the scored state has two rounds to add together.
DEFAULT_MEETING = 6


def _ids(raw):
    if not raw:
        return []
    out = []
    for part in raw.split(","):
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


@bp.route("/")
def index():
    season = queries.get_season()
    ctx = {
        "season": season,
        "palette": palette,
        "page": "tokens",
        "round_number": request.args.get("round", DEFAULT_ROUND, type=int),
    }
    if season is None:
        return render_template("styleguide/index.html", **ctx)

    round_number = ctx["round_number"]
    classification = queries.race_classification(season, round_number)
    ctx.update(
        teams=queries.teams(),
        seats=queries.seats(season),
        rounds=queries.rounds(season),
        current_round=queries.get_round(season, round_number),
        classification=classification,
        qual_final=queries.qualifying_final(season, round_number),
        fastest=queries.fastest_lap_driver(classification),
        leaders=queries.season_leaders(season),
    )
    return render_template("styleguide/index.html", **ctx)


@bp.route("/lineup")
def lineup():
    season = queries.get_season()
    state = request.args.get("state", "scored")
    sequence = request.args.get("m", DEFAULT_MEETING, type=int)
    ctx = {
        "season": season,
        "palette": palette,
        "bridge": scoring_bridge,
        "page": "lineup",
        "state": state,
        "sequence": sequence,
    }
    if season is None:
        return render_template("styleguide/lineup.html", **ctx)

    ctx["meetings"] = scoring_bridge.meetings(season)
    meeting = scoring_bridge.get_meeting(season, sequence)
    ctx["meeting"] = meeting
    if not meeting or not meeting.rounds:
        return render_template("styleguide/lineup.html", **ctx)

    first_round = min(r.round_number for r in meeting.rounds)
    roster = scoring_bridge.roster_for_round(season, first_round)
    committed = scoring_bridge.demo_lineup(roster)
    ctx["roster"] = roster

    if state == "scored":
        best = scoring_bridge.meeting_best_lineup(season, meeting)
        view = request.args.get("view")
        # The Maximum Attack route is the same screen with a different lineup
        # in it, deliberately: it is the shape the player already reads.
        subject = best.lineup if view == "best" else committed
        if subject:
            breakdowns = scoring_bridge.score_meeting(season, meeting, subject)
            picks = scoring_bridge.aggregate_meeting(breakdowns)
            scoring_bridge.mark_best(picks, best.lineup)
            ctx["picks"] = picks
            ctx["meeting_total"] = sum((p.total for p in picks), 0)
        ctx["best"] = best
        ctx["view"] = view
        ctx["open_pick"] = request.args.get("pick", type=int)
        return render_template("styleguide/lineup.html", **ctx)

    if state == "edit" and "d" not in request.args and committed:
        draft_drivers = sorted(committed.drivers)
        draft_team = committed.team_id
    else:
        draft_drivers = _ids(request.args.get("d"))
        raw_team = request.args.get("t")
        draft_team = int(raw_team) if raw_team and raw_team.isdigit() else None

    problems, cost, available = scoring_bridge.draft_status(
        roster, draft_drivers, draft_team,
        committed if state == "edit" else None,
    )

    diff = scoring_bridge.transfer_diff(
        roster,
        committed if state == "edit" else None,
        draft_drivers,
        draft_team,
    )

    # An over-budget draft is a broken rule like any other, and reads in the
    # same place and the same voice as one.
    if state == "edit" and diff.cost > available:
        problems = problems + [
            f"This costs {diff.cost} transfers and you have {available}. "
            f"Put one of your original picks back."
        ]

    ctx.update(
        diff=diff,
        confirm=request.args.get("confirm"),
        committed=committed,
        draft_drivers=draft_drivers,
        draft_team=draft_team,
        edit_drivers=[scoring_bridge.slot_view(roster, d) for d in draft_drivers],
        edit_team=scoring_bridge.team_slot_view(roster, draft_team),
        open_slot=request.args.get("open"),
        options=scoring_bridge.picker_options(roster, draft_drivers, draft_team),
        problems=problems,
        edit_cost=cost,
        available=available,
        filled=len(draft_drivers) + (1 if draft_team is not None else 0),
    )
    return render_template("styleguide/lineup.html", **ctx)


@bp.route("/meeting")
def meeting():
    season = queries.get_season()
    round_number = request.args.get("round", DEFAULT_ROUND, type=int)
    ctx = {
        "season": season,
        "palette": palette,
        "page": "meeting",
        "round_number": round_number,
    }
    if season is None:
        return render_template("styleguide/meeting.html", **ctx)

    classification = queries.race_classification(season, round_number)
    roster = scoring_bridge.roster_for_round(season, round_number)
    committed = scoring_bridge.demo_lineup(roster)
    ctx.update(
        rounds=queries.rounds(season),
        current_round=queries.get_round(season, round_number),
        classification=classification,
        fastest=queries.fastest_lap_driver(classification),
        yours=set(committed.drivers) if committed else set(),
        your_team=committed.team_id if committed else None,
    )
    return render_template("styleguide/meeting.html", **ctx)
