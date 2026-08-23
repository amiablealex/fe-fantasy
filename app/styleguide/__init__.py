"""Development-only design surface.

Registered by the app factory only when `app.debug` is true.

    /styleguide    tokens, primitives, the palette, type specimens

**Trimmed in stage 7.6.** It also carried `/styleguide/lineup` — the lineup
component in three states, meeting navigation, results and profiles — and
`/styleguide/meeting`. Every one of those is now a production screen, reached
from the application's own navigation and rendered from the same partials, so
the styleguide copies were a second implementation of six screens that would
have drifted from the real ones the first time either changed. That is the
failure §11 keeps recording, and a debug-only surface is where it would go
unnoticed longest.

`/styleguide/meeting` had already failed: its template was never committed, so
the route had been raising a 500 since Phase 3 and nobody had reason to visit
it. Which is the argument in miniature.

What remains is the part with no production equivalent: the tokens, the two
type specimens against real names, and the palette with its collision report.
Those answer "is this system coherent", which no application screen asks.
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

DEFAULT_ROUND = 1


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
