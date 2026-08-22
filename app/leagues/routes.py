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
from app.leagues import invite, service
from app.leagues.forms import (
    CreateLeagueForm,
    GlobalVisibilityForm,
    JoinLeagueForm,
    RenameLeagueForm,
)
from app.leagues.standings import standings
from app.lineups.service import current_season
from app.models.league import League
from app.models.user import User
from app.utils import client_ip

leagues_bp = Blueprint("leagues", __name__, url_prefix="/leagues")
invite_bp = Blueprint("invite", __name__)

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
    rows = []
    for league, membership in service.user_leagues(current_user):
        rows.append(
            {
                "league": league,
                "membership": membership,
                "members": service.member_count(league),
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
        return redirect(url_for("leagues.detail", league_id=league.id))
    return render_template("leagues/new.html", form=form, title="New league")


@leagues_bp.route("/join", methods=["GET", "POST"])
@login_required
def join():
    form = JoinLeagueForm()

    if request.method == "POST" and _invite_blocked():
        flash("Too many attempts. Try again shortly.", "error")
        return render_template("leagues/join.html", form=form, title="Join a league"), 429

    if form.validate_on_submit():
        league = service.league_by_code(form.filter_code())
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
    return redirect(url_for("leagues.detail", league_id=league.id))


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
            return redirect(url_for("leagues.detail", league_id=league.id))
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
        members=service.members_of(league),
        cap=service.cap(),
        season=season,
        standings=table,
        window=window,
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
        return redirect(url_for("leagues.detail", league_id=league.id))
    try:
        service.rename_league(current_user, league, form.name.data)
    except service.LeagueError as refusal:
        flash(refusal.message, "error")
        return redirect(url_for("leagues.detail", league_id=league.id))
    flash("League renamed.", "success")
    return redirect(url_for("leagues.detail", league_id=league.id))


@leagues_bp.route("/<int:league_id>/rotate", methods=["POST"])
@login_required
def rotate(league_id: int):
    league, _ = _member_league(league_id)
    try:
        service.rotate_invite_code(current_user, league)
    except service.LeagueError as refusal:
        flash(refusal.message, "error")
        return redirect(url_for("leagues.detail", league_id=league.id))
    flash("New invite code issued. Links using the old one no longer work.", "success")
    return redirect(url_for("leagues.detail", league_id=league.id))


@leagues_bp.route("/<int:league_id>/leave", methods=["POST"])
@login_required
def leave(league_id: int):
    league, _ = _member_league(league_id)
    name = league.name
    try:
        service.leave_league(current_user, league)
    except service.LeagueError as refusal:
        flash(refusal.message, "error")
        return redirect(url_for("leagues.detail", league_id=league.id))
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
        return redirect(url_for("leagues.detail", league_id=league.id))
    flash(f"{target.username} removed.", "info")
    return redirect(url_for("leagues.detail", league_id=league.id))


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
