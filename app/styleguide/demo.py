"""Fabricated data for the styleguide, and nothing else.

`demo_lineup` used to live in `scoring_bridge`, back when the proof screens
were that module's only caller. The bridge is production code from Phase 5 —
the scoring worker imports it — and a module the worker loads has no business
carrying a function that invents a lineup.

So it moved down rather than dying. The styleguide still has no user and still
needs five picks to render against; the application has real snapshots and
never calls this. It goes when the styleguide goes.
"""

from __future__ import annotations

from app.lineups.roster import Roster
from app.scoring import lineups


def demo_lineup(roster: Roster) -> lineups.Lineup | None:
    """A stand-in lineup, for screens that have no logged-in player.

    Deliberately spread across the field rather than picked for quality: four
    drivers from four different teams at intervals through the roster, so the
    breakdown shows a strong round, a weak one, and something negative rather
    than five variations on a podium.
    """
    teams_in_order = sorted(
        roster.drivers_by_team,
        key=lambda t: (roster.teams[t].name or "") if t in roster.teams else "",
    )
    if len(teams_in_order) <= lineups.DRIVER_SLOTS:
        return None

    step = max(1, len(teams_in_order) // (lineups.DRIVER_SLOTS + 1))
    chosen_teams = [teams_in_order[i * step] for i in range(lineups.DRIVER_SLOTS)]
    picked = [sorted(roster.drivers_by_team[t])[0] for t in chosen_teams]

    spare = next(t for t in teams_in_order if t not in chosen_teams)
    return lineups.Lineup.of(picked, spare)
