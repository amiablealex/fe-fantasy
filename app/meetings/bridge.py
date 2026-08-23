"""Adapter between the database and the scoring engine.

`app/scoring/` takes plain dicts and imports nothing from Flask or SQLAlchemy,
which is what lets `sim/` run without a web application. Something has to sit
between the ORM and that contract, and this is it — and now this is *only* it.

Phase 5 promoted `scoring_bridge.py` here whole, doing five jobs where it should
do one. Phase 7 split it four ways:

    bridge     this module: ORM rows -> engine dicts, and the ruleset to use
    display    every string a reader sees
    queries    reads that return display-ready shapes
    view       lineup + stored scores -> the view models a template consumes

Four rather than the three SPEC.md §8 named. `queries` holds `select()`
statements and `view` brute-forces twenty thousand lineups; a module that did
both would be the "does five jobs" problem again at smaller scale. Recorded in
the spec as a deliberate divergence.

The worker and the scoring pass want this module and nothing else in the set.

**Every call into the engine passes the round's own recorded ruleset.** Before
Phase 5 the bridge let `ruleset` default, which resolves to `CURRENT_VERSION` —
harmless while v1 was the only version in play, and a silent rewrite of history
the first time the places gained/lost magnitudes are re-tuned after Jeddah.
`Round.scoring_ruleset_version` exists for exactly this.
"""

from __future__ import annotations

from app.models.calendar import STAGE_RACE, Round
from app.scoring.rules import get_ruleset


def ruleset_for(round_obj: Round):
    """The ruleset a round must be scored against.

    Never the current one. A round records the version in force when it was
    created (SPEC.md §3), and `get_ruleset` raises on a version that no longer
    exists rather than falling back — a round whose score cannot be reproduced
    is a bug that has to be visible.
    """
    return get_ruleset(round_obj.scoring_ruleset_version)


def result_row(result) -> dict:
    """One classification row in the engine's input shape.

    Only the five keys the engine reads. Anything else would be an invitation
    for the engine to start reading it.
    """
    return {
        "driver_id": result.driver_id,
        "position": result.position,
        "grid_position": result.grid_position,
        "status": result.status,
        "lap_time": result.lap_time,
    }


# The name the old module exported. Kept because the scoring pass reaches for
# it; it was never private in practice.
_result_row = result_row


def round_payload(round_obj: Round) -> tuple[list[dict], list[dict]]:
    """(qualifying sessions, race rows) for one round, engine-shaped.

    Sessions come back in schedule order, which matters: the engine derives pole
    from the Qual Final's winner, and the final has to have landed.
    """
    qualifying: list[dict] = []
    race_rows: list[dict] = []

    for session in sorted(round_obj.sessions, key=lambda s: s.ordinal):
        rows = [result_row(r) for r in session.results]
        if session.stage == STAGE_RACE:
            race_rows = rows
        elif session.is_scoring_qualifying:
            qualifying.append({
                "stage": session.stage,
                "stage_index": session.stage_index,
                "rows": rows,
            })

    return qualifying, race_rows
