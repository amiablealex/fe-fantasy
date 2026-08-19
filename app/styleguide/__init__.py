"""Development-only design surface.

Registered by the app factory only when `app.debug` is true, so it cannot reach
production even if the blueprint is left in place.

This is the permanent regression surface for the design system: one page that
renders every token and every primitive against real Season 12 data. When a
token changes, this page shows everything the change touched.
"""

from flask import Blueprint, render_template, request

from app import palette
from app.styleguide import queries

bp = Blueprint(
    "styleguide",
    __name__,
    url_prefix="/styleguide",
    template_folder="../templates/styleguide",
)

# São Paulo. Seven retirements occupying P14 to P20, which makes it the round
# that exercises the DNF, places-lost and negative-figure patterns hardest.
DEFAULT_ROUND = 1


@bp.route("/")
def index():
    season = queries.get_season()
    ctx = {
        "season": season,
        "palette": palette,
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
