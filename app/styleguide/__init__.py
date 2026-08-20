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

from flask import Blueprint, render_template, request, url_for

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

    refs = scoring_bridge.meeting_refs(season)
    latest = scoring_bridge.latest_scored(refs)
    if "m" not in request.args and latest:
        sequence = latest
        ctx["sequence"] = sequence

    ctx.update(
        refs=refs,
        latest=latest,
        nav=scoring_bridge.neighbours(refs, sequence),
        menu=request.args.get("menu"),
    )

    meeting = scoring_bridge.get_meeting(season, sequence)
    ctx["meeting"] = meeting
    if not meeting or not meeting.rounds:
        return render_template("styleguide/lineup.html", **ctx)

    ordered_rounds = sorted(meeting.rounds, key=lambda r: r.round_number)
    ctx["meeting_rounds"] = ordered_rounds

    # Results sit in a disclosure on the same page rather than behind a tab:
    # collapsed, they cost a reader who came for their own score nothing, and
    # the round and stage switches keep the section open by carrying a marker
    # in the URL rather than needing script to remember it.
    chosen = request.args.get("r", type=int) or ordered_rounds[0].round_number
    shown = next(
        (r for r in ordered_rounds if r.round_number == chosen), ordered_rounds[0]
    )
    # Profiles open over whatever is already on screen, and close by dropping
    # the parameter — so closing one returns the picker exactly as it was.
    raw_profile = request.args.get("profile")
    ctx["profile"] = None
    ctx["profile_close"] = request.url.split("&profile=")[0]
    if raw_profile and len(raw_profile) > 1 and raw_profile[1:].isdigit():
        subject_id = int(raw_profile[1:])
        if raw_profile[0] == "d":
            ctx["profile"] = scoring_bridge.driver_profile(season, subject_id)
        elif raw_profile[0] == "t":
            ctx["profile"] = scoring_bridge.team_profile(season, subject_id)

    ctx.update(
        results=scoring_bridge.round_results(shown),
        schedule=scoring_bridge.round_schedule(shown),
        shown_round=shown,
        stage=request.args.get("stage", "race"),
        results_open=request.args.get("results") == "open",
        profile_base=(
            f"{url_for('styleguide.lineup')}?m={sequence}"
            f"&r={shown.round_number}&stage={request.args.get('stage', 'race')}"
            f"&results=open"
        ),
        profile_hx=url_for("styleguide.lineup_profile"),
    )

    # The roster is a per-round question, so it resolves against the meeting's
    # first round: a mid-season team switch means "which team is this driver
    # on" has no answer at meeting level.
    first_round = ordered_rounds[0].round_number
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


@bp.route("/lineup/profile")
def lineup_profile():
    """A profile sheet on its own, for HTMX to drop into the page.

    Opening a profile used to be a full navigation, which reloaded the meeting
    page and threw away the reader's position — tapping a driver halfway down a
    classification sent them back to the top. Swapping the dialog in leaves the
    page exactly where it was, so closing returns you to the row you tapped.

    The links keep their plain href, so this still works without JavaScript;
    that path navigates, as it did before.
    """
    season = queries.get_season()
    raw = request.args.get("subject", "")
    if season is None or len(raw) < 2 or not raw[1:].isdigit():
        return "", 204

    subject_id = int(raw[1:])
    if raw[0] == "d":
        profile = scoring_bridge.driver_profile(season, subject_id)
    elif raw[0] == "t":
        profile = scoring_bridge.team_profile(season, subject_id)
    else:
        profile = None

    if profile is None:
        return "", 204

    return render_template(
        "styleguide/_profile_sheet.html",
        bridge=scoring_bridge,
        palette=palette,
        profile=profile,
        close_url=request.args.get("back") or url_for("styleguide.lineup"),
    )


@bp.route("/lineup/results")
def lineup_results():
    """The Results disclosure body, on its own.

    HTMX swaps this fragment in rather than reloading the meeting page, which
    is what stops a round or stage switch throwing away the reader's scroll
    position. It renders the same template the full page includes, so the two
    cannot drift.
    """
    season = queries.get_season()
    sequence = request.args.get("m", DEFAULT_MEETING, type=int)
    meeting = scoring_bridge.get_meeting(season, sequence) if season else None
    if not meeting or not meeting.rounds:
        return "", 204

    ordered = sorted(meeting.rounds, key=lambda r: r.round_number)
    chosen = request.args.get("r", type=int) or ordered[0].round_number
    shown = next((r for r in ordered if r.round_number == chosen), ordered[0])

    return render_template(
        "styleguide/_results_body.html",
        palette=palette,
        base=url_for("styleguide.lineup"),
        sequence=sequence,
        meeting_rounds=ordered,
        shown_round=shown,
        stage=request.args.get("stage", "race"),
        results=scoring_bridge.round_results(shown),
        schedule=scoring_bridge.round_schedule(shown),
        profile_base=(
            f"{url_for('styleguide.lineup')}?m={sequence}"
            f"&r={shown.round_number}&stage={request.args.get('stage', 'race')}"
            f"&results=open"
        ),
        profile_hx=url_for("styleguide.lineup_profile"),
    )


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
