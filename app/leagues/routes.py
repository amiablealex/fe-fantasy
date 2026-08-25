"""League routes: the lifecycle, and the invite landing.

Two blueprints. `leagues_bp` is everything under `/leagues`. `invite_bp` holds
one route at `/join/<code>`, outside the prefix, because that URL gets pasted
into a group chat and `fe.kitsniff.com/join/K7M2QX` is a link someone will
actually tap.

**Not a member is 404, not 403.** A 403 on `/leagues/12` tells whoever asked
that league 12 exists, which is the same leak the friend profile avoids.

**Every rule lives in the service.** These functions read a form, call one
function, and flash the sentence it refused with. Nothing here decides who may
do what.
"""
from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.auth import rate_limit
from app.clock import now
from app.extensions import db
from app.leagues import invite, service, visibility
from app.leagues.forms import (
    CreateLeagueForm,
    GlobalVisibilityForm,
    JoinLeagueForm,
    RenameLeagueForm,
)
from app.leagues.profile import player_profile, weekend_detail
from app.meetings import display as bridge
from app.meetings import queries as meeting_queries
from app.meetings.routes import results_context
from app.leagues.standings import standings, standings_for_user
from app.lineups.service import current_season
from app import palette
from app.models.league import League
from app.models.user import User
from app.utils import client_ip

leagues_bp = Blueprint("leagues", __name__, url_prefix="/leagues")
invite_bp = Blueprint("invite", __name__)

# Outside the /leagues prefix. A profile is reached from a league table, but it
# is not scoped to one — the same player seen through two shared leagues is the
# same season, and a per-league URL would say otherwise.
players_bp = Blueprint("players", __name__)

# Shared by the landing and the code form: both are the same guessing attack
# from the same address, and giving them separate allowances would halve the
# protection for no reason.
BUCKET_INVITE = "invite"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _invite_blocked() -> bool:
    return rate_limit.is_blocked(BUCKET_INVITE, client_ip())


def _record_bad_code() -> None:
    """Count a miss. A code that resolves is never counted.

    The bucket exists to stop enumeration of a six-character space, and a
    member following their own working link repeatedly is not that.
    """
    cfg = current_app.config
    rate_limit.record_failure(
        BUCKET_INVITE,
        client_ip(),
        max_attempts=cfg["INVITE_MAX_ATTEMPTS"],
        window_minutes=cfg["INVITE_WINDOW_MINUTES"],
        block_minutes=cfg["INVITE_BLOCK_MINUTES"],
    )


def _member_league(league_id: int):
    """A league the signed-in user belongs to, or 404."""
    league = db.session.get(League, league_id)
    if league is None:
        abort(404)
    membership = service.membership_of(current_user, league)
    if membership is None:
        abort(404)
    return league, membership


def _share_url(league) -> str:
    return url_for("invite.landing", code=league.invite_code, _external=True)


# The range control offers three options and the URL accepts exactly those.
# Leaving it open would mean `?last=1000` renders a "last 1000 weekends"
# heading, which is a small thing that reads as a broken page.
WINDOWS = (3, 5)


def _window() -> int | None:
    raw = request.args.get("last")
    if raw and raw.isdigit() and int(raw) in WINDOWS:
        return int(raw)
    return None


# -----------------------------------------------------------------------------
# The list
# -----------------------------------------------------------------------------


@leagues_bp.route("/")
@login_required
def index():
    """Every league you are in, and where you are in each of them.

    Off-season the only fact a league has is how many people are in it. Once a
    weekend has scored, that is no longer the interesting one — a member count
    is a property of the league, and this page is a list of the reader's own
    leagues, so it should answer the question they came with: how am I doing in
    each. The count stays, one line down, because "of 50" is also how you know
    whether there is room for another friend.

    `standings_for_user` is the same aggregate the front page's standing block
    reads, so the two cannot disagree about a position — the front page already
    made this exact query and this is its second caller rather than a second
    implementation.
    """
    season = current_season()
    placings = {}
    if season is not None:
        placings = {
            standing.league.id: standing
            for standing in standings_for_user(current_user, season, now=now())
        }

    rows = []
    for league, membership in service.user_leagues(current_user):
        rows.append(
            {
                "league": league,
                "membership": membership,
                "members": service.member_count(league),
                "standing": placings.get(league.id),
            }
        )
    return render_template(
        "leagues/index.html",
        rows=rows,
        cap=service.cap(),
        title="Leagues",
    )


# -----------------------------------------------------------------------------
# Create and join
# -----------------------------------------------------------------------------


@leagues_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    form = CreateLeagueForm()
    if form.validate_on_submit():
        try:
            league = service.create_league(current_user, form.name.data)
        except service.LeagueError as refusal:
            flash(refusal.message, "error")
            return redirect(url_for("leagues.new"))
        flash(f"{league.name} created. Share the code to invite people.", "success")
        return redirect(url_for("leagues.settings", league_id=league.id))
    return render_template("leagues/new.html", form=form, title="New league")


@leagues_bp.route("/join", methods=["GET", "POST"])
@login_required
def join():
    form = JoinLeagueForm()

    if request.method == "POST" and _invite_blocked():
        flash("Too many attempts. Try again shortly.", "error")
        return render_template("leagues/join.html", form=form, title="Join a league"), 429

    if form.validate_on_submit():
        league = service.league_by_code(form.code.data)
        if league is None:
            _record_bad_code()
            flash("No league has that code.", "error")
            return redirect(url_for("leagues.join"))
        return _attempt_join(league)

    return render_template("leagues/join.html", form=form, title="Join a league")


def _attempt_join(league):
    try:
        service.join_league(current_user, league)
    except service.LeagueError as refusal:
        flash(refusal.message, "error")
        return redirect(url_for("leagues.index"))
    flash(f"You have joined {league.name}.", "success")
    return redirect(url_for("leagues.settings", league_id=league.id))


@invite_bp.route("/join/<code>")
def landing(code: str):
    """An invite link, followed by anyone.

    Signed in, it joins. Signed out, it names the league and holds the code
    through registration — arriving at a bare sign-in page having tapped an
    invite is how people conclude the link was broken.
    """
    if _invite_blocked():
        return render_template("leagues/landing.html", league=None, title="Invite"), 429

    league = service.league_by_code(code)
    if league is None:
        _record_bad_code()
        invite.forget()
        if current_user.is_authenticated:
            flash("That invite link is no longer valid.", "error")
            return redirect(url_for("leagues.index"))
        return render_template("leagues/landing.html", league=None, title="Invite"), 404

    if current_user.is_authenticated:
        invite.forget()
        if service.membership_of(current_user, league) is not None:
            return redirect(url_for("leagues.settings", league_id=league.id))
        return _attempt_join(league)

    invite.remember(league.invite_code)
    return render_template(
        "leagues/landing.html",
        league=league,
        full=service.is_full(league),
        title="Invite",
    )


# -----------------------------------------------------------------------------
# One league
# -----------------------------------------------------------------------------


@leagues_bp.route("/<int:league_id>")
@login_required
def detail(league_id: int):
    """The table, and nothing else.

    This page used to carry seven regions: the table, the membership list, the
    invite code, the share link, a rename form and two destructive controls.
    They are two different visits wearing one URL — reading the standings, and
    administering the league — and only one of them is why anybody opens a
    league on a Sunday night.

    The membership list was also a near-duplicate of the table: the same people,
    in a different order, one screen apart. Everything unique to it — join
    dates, who is hidden, the remove control — is administration. So moving it
    removed a duplication rather than merely hiding one.
    """
    league, membership = _member_league(league_id)
    season = current_season()
    window = _window()

    table = None
    if season is not None:
        table = standings(
            league, season, viewer=current_user, now=now(), window=window
        )

    return render_template(
        "leagues/detail.html",
        league=league,
        membership=membership,
        # The count, not the list. A template holding the members is a template
        # that will end up rendering them again.
        member_count=len(service.members_of(league)),
        cap=service.cap(),
        season=season,
        standings=table,
        window=window,
        title=league.name,
    )


@leagues_bp.route("/<int:league_id>/settings")
@login_required
def settings(league_id: int):
    """Everything you do *to* a league, as opposed to read from it.

    Membership, the invite, the name, and leaving. Visible to every member
    rather than to admins only: a member still needs the code to invite a
    friend, still wants to see who is in, and must always be able to leave.
    Which controls appear is the template's business and it asks `membership`.

    No season, no standings, no window. Nothing on this page changes between
    weekends, which is the clearest sign it did not belong on one that does.
    """
    league, membership = _member_league(league_id)
    return render_template(
        "leagues/settings.html",
        league=league,
        membership=membership,
        members=service.members_of(league),
        cap=service.cap(),
        share_url=None if league.is_global else _share_url(league),
        rename_form=RenameLeagueForm(name=league.name),
        title=league.name,
    )


@leagues_bp.route("/<int:league_id>/rename", methods=["POST"])
@login_required
def rename(league_id: int):
    league, _ = _member_league(league_id)
    form = RenameLeagueForm()
    if not form.validate_on_submit():
        flash("A league name is between 2 and 80 characters.", "error")
        return redirect(url_for("leagues.settings", league_id=league.id))
    try:
        service.rename_league(current_user, league, form.name.data)
    except service.LeagueError as refusal:
        flash(refusal.message, "error")
        return redirect(url_for("leagues.settings", league_id=league.id))
    flash("League renamed.", "success")
    return redirect(url_for("leagues.settings", league_id=league.id))


@leagues_bp.route("/<int:league_id>/rotate", methods=["POST"])
@login_required
def rotate(league_id: int):
    league, _ = _member_league(league_id)
    try:
        service.rotate_invite_code(current_user, league)
    except service.LeagueError as refusal:
        flash(refusal.message, "error")
        return redirect(url_for("leagues.settings", league_id=league.id))
    flash("New invite code issued. Links using the old one no longer work.", "success")
    return redirect(url_for("leagues.settings", league_id=league.id))


@leagues_bp.route("/<int:league_id>/leave", methods=["POST"])
@login_required
def leave(league_id: int):
    league, _ = _member_league(league_id)
    name = league.name
    try:
        service.leave_league(current_user, league)
    except service.LeagueError as refusal:
        flash(refusal.message, "error")
        return redirect(url_for("leagues.settings", league_id=league.id))
    flash(f"You have left {name}.", "info")
    return redirect(url_for("leagues.index"))


@leagues_bp.route("/<int:league_id>/members/<int:user_id>/remove", methods=["POST"])
@login_required
def remove(league_id: int, user_id: int):
    league, _ = _member_league(league_id)
    target = db.session.get(User, user_id)
    if target is None:
        abort(404)
    try:
        service.remove_member(current_user, league, target)
    except service.LeagueError as refusal:
        flash(refusal.message, "error")
        return redirect(url_for("leagues.settings", league_id=league.id))
    flash(f"{target.username} removed.", "info")
    return redirect(url_for("leagues.settings", league_id=league.id))


# -----------------------------------------------------------------------------
# The account toggle
# -----------------------------------------------------------------------------


@leagues_bp.route("/global/visibility", methods=["POST"])
@login_required
def global_visibility():
    """Posted from the account page, because that is where it reads as a setting.

    The route lives here rather than in `auth` so that no part of the auth
    blueprint has to know what a hidden membership is.
    """
    form = GlobalVisibilityForm()
    if form.validate_on_submit():
        service.set_global_hidden(current_user, hidden=not form.show.data)
        flash(
            "You are shown on the global league."
            if form.show.data
            else "You are hidden from the global league.",
            "success",
        )
    return redirect(url_for("auth.account"))


# -----------------------------------------------------------------------------
# Friend profiles
# -----------------------------------------------------------------------------


@players_bp.route("/players/<int:user_id>")
@login_required
def profile(user_id: int):
    """Another player's season.

    404 for a player you share no league with, and 404 for one who does not
    exist. The same answer to both, because a 403 confirms the account.

    The page opens on the most recent weekend the player has a lineup for.
    `?m=<sequence>` selects another, and a sequence outside the visible list
    simply falls back to the default rather than erroring — the list is the
    gate, so an unlocked weekend cannot be reached by editing the URL.
    """
    subject = visibility.visible_user(current_user, user_id)
    if subject is None:
        abort(404)

    season = current_season()
    ctx = {"palette": palette, "bridge": bridge, "season": season,
           "subject": subject, "profile": None, "detail": None,
           "refs": [], "nav": None, "subject_profile": None}
    if season is None:
        return render_template("players/profile.html", title=subject.username, **ctx)

    moment = now()
    summary = player_profile(current_user, subject, season, now=moment)
    ctx["profile"] = summary

    raw = request.args.get("m")
    selected = None
    if raw and raw.isdigit():
        row = summary.row_for(int(raw))
        selected = row.meeting if row else None
    if selected is None:
        selected = summary.latest_with_lineup

    if selected is not None:
        ctx["detail"] = weekend_detail(
            current_user, subject, season, selected, now=moment
        )

    # Arrow navigation, promoted from the styleguide rather than rebuilt — the
    # same path `_lineup.html` and the scoring bridge took. The refs are built
    # from the *visible* weekends rather than from the calendar, so an unlocked
    # weekend has no arrow pointing at it and the nav cannot become a second
    # route to something the visibility layer hides.
    ctx["refs"] = _profile_refs(summary)
    if selected is not None:
        ctx["nav"] = meeting_queries.neighbours(ctx["refs"], selected.sequence)
        ctx["sequence"] = selected.sequence
    ctx["menu"] = request.args.get("menu")

    # Driver and team profiles open over the page here exactly as they do on the
    # weekend view, so a reader can ask "who is this" from a breakdown without
    # leaving the player they were looking at.
    raw_subject = request.args.get("profile")
    if raw_subject and len(raw_subject) > 1 and raw_subject[1:].isdigit():
        subject_id = int(raw_subject[1:])
        if raw_subject[0] == "d":
            ctx["subject_profile"] = meeting_queries.driver_profile(season, subject_id)
        elif raw_subject[0] == "t":
            ctx["subject_profile"] = meeting_queries.team_profile(season, subject_id)
    ctx["profile_close"] = request.url.split("&profile=")[0]

    # The classification, under their lineup, with their picks marked. Same
    # template the weekend view includes and the same shape a reader learns
    # once — only `base` and the marks differ, because the mark always belongs
    # to the lineup rendered directly above it.
    if selected is not None:
        ctx.update(results_context(
            selected,
            selected.sequence,
            ctx["detail"].marked if ctx["detail"] else frozenset(),
            base=url_for("players.profile", user_id=subject.id),
        ))
        ctx["results_open"] = request.args.get("results") == "open"

    return render_template(
        "players/profile.html", title=subject.username, **ctx
    )


@players_bp.route("/players/<int:user_id>/results")
@login_required
def player_results(user_id: int):
    """The Results disclosure body, for HTMX to swap in place.

    Same visibility gate as the page: a weekend not in the player's visible list
    is not reachable here either, so this cannot become the endpoint that
    forgets the deadline.
    """
    subject = visibility.visible_user(current_user, user_id)
    season = current_season()
    if subject is None or season is None:
        return "", 204

    summary = player_profile(current_user, subject, season, now=now())
    raw = request.args.get("m")
    row = summary.row_for(int(raw)) if raw and raw.isdigit() else None
    if row is None:
        return "", 204

    detail = weekend_detail(
        current_user, subject, season, row.meeting, now=now()
    )
    ctx = results_context(
        row.meeting,
        row.meeting.sequence,
        detail.marked if detail else frozenset(),
        base=url_for("players.profile", user_id=subject.id),
    )
    if not ctx:
        return "", 204
    return render_template(
        "meetings/_results_body.html", palette=palette, bridge=bridge, **ctx
    )


def _profile_refs(summary) -> list:
    """This player's visible weekends, in calendar order, as nav entries.

    `MeetingRef` carries optional `points` and `note`, which the weekend view
    leaves unset. Here they are the point: the menu behind the name is also the
    season at a glance, so it shows what each weekend scored and what it cost in
    transfers. That replaces the separate "By weekend" list, which was a second
    place to read the same rows.

    The transfer cost is the stored slot diff for a locked weekend — a past
    fact. Never the transfer *bank*, which moves the moment they commit for the
    open weekend and would leak whether they have.
    """
    refs = []
    for row in sorted(summary.weekends, key=lambda r: r.meeting.sequence):
        if row.committed and row.transfer_cost:
            note = f"{row.transfer_cost} transfer" + (
                "" if row.transfer_cost == 1 else "s"
            )
        elif row.snapshot is None:
            note = "No lineup"
        else:
            note = None
        refs.append(meeting_queries.MeetingRef(
            sequence=row.meeting.sequence,
            name=row.meeting.display_name,
            scored=row.scored,
            provisional=False,
            rounds=[r.round_number for r in row.meeting.rounds],
            points=row.points,
            note=note,
        ))
    return refs
