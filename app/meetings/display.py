"""How a score is worded.

One of the four modules `scoring_bridge` became. This one owns every string a
reader sees that is not stored in the database: rule names, the sentences under
a breakdown, the abbreviations at the head of a profile column, and the
formatting of a figure.

**This module imports the engine and nothing else.** No SQLAlchemy, no Flask, no
models. That is the same guarantee `app/scoring/` carries and it is tested the
same way, for the same reason: wording is what changes most often and what is
hardest to test, so it should be the cheapest thing in the project to import.

The engine has no business knowing how a rule is phrased in an interface, and
a template has no business deriving a phrase from a rule key. This is where the
two meet.

**Fantasy points, and only fantasy points.** Everything this module formats is a
figure produced by `app/scoring/`. The provider's own championship points are
stored (§6's ingest sanity check compares against them) and are never rendered
anywhere in the application. There is one unit in this app and it is FP.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.scoring import engine

# -----------------------------------------------------------------------------
# The unit
# -----------------------------------------------------------------------------

# The name of the only kind of point this app has. Real Formula E championship
# points are ingested for cross-validation and are never shown, so there is no
# second unit to disambiguate against — but naming it explicitly is what stops
# a column heading ever reading "Points" and leaving the reader to guess which.
POINTS_ABBREVIATION = "FP"
POINTS_NAME = "Fantasy points"

# What the best possible lineup for a weekend is called. Real racing vernacular
# rather than a generic superlative, and one constant so renaming it is one
# edit.
DREAM_TEAM_NAME = "Perfect Five"


# -----------------------------------------------------------------------------
# Rules
# -----------------------------------------------------------------------------

# Rule identifiers are stable keys; these are what a person reads.
RULE_LABELS: dict[str, str] = {
    engine.RULE_GROUP_PROGRESS: "Reached the Duels",
    engine.RULE_DUEL_WIN: "Duel win",
    engine.RULE_POLE: "Pole position",
    engine.RULE_WIN: "Race win",
    engine.RULE_PODIUM: "Podium",
    engine.RULE_POINTS_FINISH: "Points finish",
    engine.RULE_FASTEST_LAP: "Fastest lap",
    engine.RULE_PLACES_GAINED: "Places gained",
    engine.RULE_PLACES_LOST: "Places lost",
}


def rule_label(rule: str) -> str:
    return RULE_LABELS.get(rule, rule.replace("_", " ").capitalize())


# The qualifying rules, as a set, so a caller can split a component list into
# the two contests without restating which is which. `aggregate_meeting` needs
# exactly this and used to carry its own copy.
QUALIFYING_RULES = frozenset({
    engine.RULE_GROUP_PROGRESS,
    engine.RULE_DUEL_WIN,
    engine.RULE_POLE,
})


def split_components(components) -> tuple[tuple, tuple]:
    """(qualifying, race), preserving order within each."""
    qualifying = tuple(c for c in components if c.rule in QUALIFYING_RULES)
    race = tuple(c for c in components if c.rule not in QUALIFYING_RULES)
    return qualifying, race


# -----------------------------------------------------------------------------
# Profile columns
# -----------------------------------------------------------------------------
#
# One wide table: every scoring route as a column, every round as a row, totals
# in bold at the foot. Not split by contest, because the question the page
# exists to answer is "how has this driver scored across the season" and a split
# gives two grand totals instead of one.
#
# Eleven columns fit a 360px viewport at --step-1 in condensed tabular figures —
# measured, not assumed. What makes it readable is not the width but suppressing
# zeros: nine columns of "0" is noise, and a blank makes the cells that fired
# legible at a glance.

# Column order groups qualifying then race, so the conceptual split survives
# without the table being cut in two.
PROFILE_COLUMNS = [
    (engine.RULE_GROUP_PROGRESS, "GRP", "Reached the Duels"),
    (engine.RULE_DUEL_WIN, "DW", "Duel wins"),
    (engine.RULE_POLE, "POL", "Pole position"),
    (engine.RULE_WIN, "WIN", "Race win"),
    (engine.RULE_PODIUM, "POD", "Podium"),
    (engine.RULE_POINTS_FINISH, "PTS", "Points finish"),
    (engine.RULE_FASTEST_LAP, "FL", "Fastest lap"),
    ("places", "±PL", "Places gained or lost"),
]

# Where the qualifying columns end, for the divider rule.
PROFILE_QUALIFYING_COLUMNS = 3

# Places gained and lost are one mechanic with a sign, so they share a column.
# Two columns, one of which is always empty, wastes width for no information.
PLACES_RULES = (engine.RULE_PLACES_GAINED, engine.RULE_PLACES_LOST)

# Backwards-compatible alias; the private name was reached from the old module.
_PLACES_RULES = PLACES_RULES


def profile_column_key(rule: str) -> str:
    """Which profile column a rule lands in."""
    return "places" if rule in PLACES_RULES else rule


# -----------------------------------------------------------------------------
# Figures
# -----------------------------------------------------------------------------

_PLACES_DETAIL = re.compile(r"P(\d+)\s+to\s+P(\d+)")


def fmt(value) -> str:
    """A score, as a reader expects to see it.

    Halves are real and must survive — the team pick genuinely scores 5.5, and
    SPEC.md §3 forbids rounding because it introduces a bias that then needs
    explaining. But a Decimal's trailing zero is an artefact of arithmetic, not
    a fact about the score, and "25" one weekend against "26.0" the next reads
    as two different kinds of number.

    So: strip a trailing .0, keep a genuine .5.
    """
    if value is None:
        return "—"
    text = f"{Decimal(value):f}"
    # Only strip inside a fraction: rstrip on "20" would give "2".
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def component_detail(component) -> str | None:
    """The detail line for one scoring component.

    Places gained and lost are rewritten: the engine emits "P13 to P5", but the
    stage's context line already says "Started P13 · finished P5", so repeating
    it wastes the row. What the reader wants there is the figure the rule
    actually counted — eight places — because that is what produced the points.

    Rewritten here rather than in the engine because it is wording, and the
    engine has no business knowing how a rule is phrased in an interface.
    """
    detail = getattr(component, "detail", None)
    if not detail:
        return None
    if component.rule in PLACES_RULES:
        match = _PLACES_DETAIL.search(str(detail))
        if match:
            gained = abs(int(match.group(1)) - int(match.group(2)))
            return f"{gained} places"
    return detail


# -----------------------------------------------------------------------------
# Context
# -----------------------------------------------------------------------------
#
# A breakdown that says only "no rules fired" is a non-answer: it cannot
# distinguish a driver who qualified fifteenth from one who was not on the grid
# at all. Both sections of a breakdown therefore always carry a plain sentence
# about what happened, with the scoring rows beneath it, so a zero is legible as
# a result rather than as an absence.
#
# This is derived from the raw payload rather than from the engine. Making the
# engine emit zero-point components would corrupt what "which rules fired" means
# and break `DriverRoundScore.fired()`, so the wording is this module's job.

_GROUP_LETTERS = {1: "A", 2: "B", 3: "C", 4: "D"}

_DUEL_LABELS = {
    engine.STAGE_QUARTER_FINAL: "Quarter-Final",
    engine.STAGE_SEMI_FINAL: "Semi-Final",
    engine.STAGE_FINAL: "Final",
}


def group_letter(stage_index) -> str:
    """Group 1 is Group A. Used by the bracket as well as by the context line."""
    return _GROUP_LETTERS.get(stage_index, "")


def duel_label(stage: str, stage_index=None) -> str:
    label = _DUEL_LABELS.get(stage, stage.replace("_", " ").title())
    return f"{label} {stage_index}" if stage_index else label


def _row_for(rows, driver_id):
    for row in rows:
        if row.get("driver_id") == driver_id:
            return row
    return None


def qualifying_context(qualifying_sessions, driver_id) -> str | None:
    """How far a driver got in the bracket, in one sentence.

    None means they do not appear in qualifying at all, which is a different
    thing from scoring zero and must read differently.
    """
    seen = False
    group_note = None

    for session in qualifying_sessions:
        if session.get("stage") != engine.STAGE_GROUP:
            continue
        row = _row_for(session.get("rows") or [], driver_id)
        if row is None:
            continue
        seen = True
        letter = group_letter(session.get("stage_index"))
        position = row.get("position")
        group_note = f"Group {letter}".strip() + (f" P{position}" if position else "")

    # Walk the bracket outwards; the last stage they appear in is where they
    # stopped, and whether they won it says whether they stopped by losing.
    furthest = None
    for stage in (engine.STAGE_QUARTER_FINAL, engine.STAGE_SEMI_FINAL,
                  engine.STAGE_FINAL):
        for session in qualifying_sessions:
            if session.get("stage") != stage:
                continue
            row = _row_for(session.get("rows") or [], driver_id)
            if row is None:
                continue
            seen = True
            furthest = (stage, row.get("position"))

    if not seen:
        return None

    if furthest is None:
        return f"Eliminated in {group_note}" if group_note else "Eliminated in the groups"

    stage, position = furthest
    label = _DUEL_LABELS.get(stage, stage)
    if stage == engine.STAGE_FINAL and position == 1:
        return "Won the Final — pole position"
    if position == 1:
        return f"Won the {label}"
    return f"Lost the {label}"


def race_context(race_rows, driver_id) -> str | None:
    """Started where, finished where. None if the driver did not start."""
    row = _row_for(race_rows, driver_id)
    if row is None:
        return None

    grid = row.get("grid_position")
    position = row.get("position")
    start = f"Started P{grid}" if grid else None

    if row.get("status"):
        end = f"retired, classified P{position}" if position else "retired"
    elif position:
        end = f"finished P{position}"
    else:
        end = "not classified"

    return f"{start} \u00b7 {end}" if start else end.capitalize()
