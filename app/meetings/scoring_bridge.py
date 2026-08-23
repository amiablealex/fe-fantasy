"""Compatibility shim. **Deleted in stage 7.5.**

This module used to be nine hundred lines doing five jobs. Stage 7.1 split it:

    app/meetings/bridge.py     ORM rows -> engine dicts, and the ruleset to use
    app/meetings/display.py    every string a reader sees
    app/meetings/queries.py    reads that return display-ready shapes
    app/meetings/view.py       lineup + stored scores -> template view models

Nothing lives here any more. What remains is a re-export, so callers that have
not yet been rewritten keep working while the phase moves through them one at a
time — the split and the rewrite of a dozen call sites are separate mistakes to
make, and doing them in one commit would make a regression impossible to
bisect.

**Do not import this in new code.** Import the module that owns what you want.
When `grep -rn "scoring_bridge" --include=*.py --include=*.html` comes back
empty except for this file, delete the file.
"""

from __future__ import annotations

# Re-exported for callers that reached them through this module.
from app.lineups.roster import Roster, roster_for_round, seat_entries
from app.meetings.bridge import _result_row, result_row, round_payload, ruleset_for
from app.meetings.display import (
    DREAM_TEAM_NAME,
    PLACES_RULES,
    PROFILE_COLUMNS,
    PROFILE_QUALIFYING_COLUMNS,
    RULE_LABELS,
    component_detail,
    fmt,
    qualifying_context,
    race_context,
    rule_label,
)
from app.meetings.queries import (
    MeetingRef,
    Neighbours,
    Profile,
    ProfileRow,
    RoundResults,
    ScheduledSession,
    StageResults,
    driver_profile,
    get_meeting,
    latest_scored,
    meeting_refs,
    meetings,
    neighbours,
    round_results,
    round_schedule,
    season_scores,
    team_profile,
)
from app.meetings.view import (
    BestLineup,
    PickMeetingScore,
    PickScore,
    RoundBreakdown,
    RoundDetail,
    aggregate_meeting,
    mark_best,
    meeting_best_lineup,
    score_meeting,
)

# pyflakes flags a re-export as an unused import and has no `# noqa`. Naming
# every symbol here is how the module says the imports are the point.
__all__ = [
    "BestLineup",
    "DREAM_TEAM_NAME",
    "MeetingRef",
    "Neighbours",
    "PLACES_RULES",
    "PROFILE_COLUMNS",
    "PROFILE_QUALIFYING_COLUMNS",
    "PickMeetingScore",
    "PickScore",
    "Profile",
    "ProfileRow",
    "RULE_LABELS",
    "Roster",
    "RoundBreakdown",
    "RoundDetail",
    "RoundResults",
    "ScheduledSession",
    "StageResults",
    "_result_row",
    "aggregate_meeting",
    "component_detail",
    "driver_profile",
    "fmt",
    "get_meeting",
    "latest_scored",
    "mark_best",
    "meeting_best_lineup",
    "meeting_refs",
    "meetings",
    "neighbours",
    "qualifying_context",
    "race_context",
    "result_row",
    "roster_for_round",
    "round_payload",
    "round_results",
    "round_schedule",
    "rule_label",
    "ruleset_for",
    "score_meeting",
    "season_scores",
    "seat_entries",
    "team_profile",
]
