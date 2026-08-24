"""Static pages: how the game works, what this is, and the legal minimum.

Four routes, no database, no login required. They exist because friends will
register in December knowing nothing about scoring beyond one sentence on the
signed-out landing, and because a public registration form with no privacy or
terms page is a gap rather than a nicety.

**The scoring page renders from the ruleset, never from typed prose.** SPEC.md
§3 versions `ScoringRuleset` precisely so the re-tune after Jeddah does not
rewrite December, and a hand-typed table of point values starts lying the day
that re-tune ships. `get_ruleset()` with no argument is correct here and only
here: this page describes how a lineup picked *today* will score, which is the
current ruleset by definition. Everywhere else in the application passes a
round's own recorded version.

Content lands in stage 8.5. Until then these are the routes and the shape.
"""
from __future__ import annotations

from flask import Blueprint, render_template

from app.meetings import display as bridge
from app.scoring.rules import get_ruleset

pages_bp = Blueprint("pages", __name__, template_folder="../templates/pages")


@pages_bp.route("/how-to-play")
def how_to_play():
    return render_template(
        "pages/how_to_play.html",
        title="How to play",
        rules=get_ruleset(),
        bridge=bridge,
    )


@pages_bp.route("/about")
def about():
    return render_template("pages/about.html", title="About")


@pages_bp.route("/privacy")
def privacy():
    return render_template("pages/privacy.html", title="Privacy")


@pages_bp.route("/terms")
def terms():
    return render_template("pages/terms.html", title="Terms")
