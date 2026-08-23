"""The qualifying bracket, as something a 360px column can hold.

The hardest visual problem in the project (SPEC.md §1) and the open risk Phase 3
recorded rather than resolved. Formula E qualifying is 20 drivers, two groups of
ten, the top four of each into a knockout of four quarter-finals, two semis and
a final. Drawn as a conventional left-to-right tree that is four columns wide
before a name is set, and a phone has room for about two.

**So it is not drawn as a tree.** It is read down the page in the order it
happened: groups, then quarter-finals, then semis, then the final. Each stage is
its own small classification, and the tree structure falls out of two things
that need no lines — a driver only appears in the next stage if they won this
one, and the losing row of every pair is dimmed and terminal.

That is close to the linear stage list Phase 3 shipped as an interim, which is
the point. The interim turned out to be the right representation; what it was
missing was not a diagram, it was **what each stage was worth**.

Three things this module adds to the raw classification:

**Points per stage, not per driver.** A driver's qualifying total accumulates
across the bracket, so a running figure on each row would invite the reader to
add rows that are already summed and get the wrong answer. Each row instead
carries what *that stage* awarded, which makes addition the correct operation:
2 to reach the Duels, 1 for each duel won, 3 for pole. Summed per driver they
equal the qualifying total in the profile, and added to the race table's FP they
equal the round.

**Deltas rather than absolutes below the leader.** "+0.161" is the fact a reader
wants from a duel; the absolute is noise once the leader's time is on the row
above.

**An explicit cut in the group stage.** Ten rows where four progress needs one
line saying so, not ten rows each captioned.

The points here are derived from position plus the round's own recorded
`ScoringRuleset` rather than read back from the stored components, because
`ScoreComponent` records which *rule* fired and not which session — attributing
a duel win to QF3 rather than SF1 would mean parsing a detail string written for
humans. Magnitudes therefore cannot drift, because both this and the engine read
the same ruleset object. Structure is pinned by a test asserting these figures
sum, per driver, to `engine.score_qualifying`'s own total.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.meetings import display
from app.scoring.engine import (
    GROUP_PROGRESSION_CUTOFF,
    STAGE_FINAL,
    STAGE_GROUP,
    STAGE_QUARTER_FINAL,
    STAGE_SEMI_FINAL,
    parse_lap_time,
)

ZERO = Decimal(0)

# The order the bracket is read in, and the heading each section carries.
SECTIONS = (
    (STAGE_GROUP, "Groups"),
    (STAGE_QUARTER_FINAL, "Quarter-Finals"),
    (STAGE_SEMI_FINAL, "Semi-Finals"),
    (STAGE_FINAL, "Final"),
)

DUEL_STAGES = (STAGE_QUARTER_FINAL, STAGE_SEMI_FINAL, STAGE_FINAL)


@dataclass(frozen=True)
class BracketRow:
    driver_id: Any
    driver: Any
    team: Any
    position: int | None
    # The leader's own time; everyone below carries a delta to it instead.
    time: str | None
    delta: str | None
    progressed: bool
    is_pole: bool
    points: Decimal

    @property
    def eliminated(self) -> bool:
        """Dimmed and terminal.

        Ink rather than opacity: opacity would dull the team stripe, and the
        stripe is the recognition aid — it has to stay at full strength whether
        or not the driver went out.
        """
        return not self.progressed


@dataclass(frozen=True)
class BracketStage:
    stage: str
    label: str
    rows: list[BracketRow]
    # Groups only: how many of the rows progressed, so the cut can be drawn
    # once as a rule rather than captioned on every row.
    cut_after: int | None = None

    @property
    def is_duel(self) -> bool:
        return self.stage in DUEL_STAGES


@dataclass(frozen=True)
class BracketSection:
    title: str
    stages: list[BracketStage] = field(default_factory=list)


def _time_of(row) -> str | None:
    """A qualifying lap time.

    `display_time` first: in a duel `lap_time` is null and `display_time`
    carries the lap (Appendix A). Falling back the other way would show a blank
    on every duel row.
    """
    return getattr(row, "display_time", None) or getattr(row, "lap_time", None)


def _delta_to(leader: str | None, value: str | None) -> str | None:
    """The gap to the session leader, or None when either time is unusable.

    Parsed rather than string-compared. Comparing the raw strings happens to
    work today only because every Formula E lap is a single-digit minute, which
    is a property of the current circuits rather than a guarantee.
    """
    if not leader or not value:
        return None
    a, b = parse_lap_time(leader), parse_lap_time(value)
    if a is None or b is None or b <= a:
        return None
    return f"+{b - a:.3f}"


def _stage_label(stage: str, index: int | None) -> str:
    if stage == STAGE_GROUP:
        letter = display.group_letter(index)
        return f"Group {letter}" if letter else "Group"
    return display.duel_label(stage, index)


def _group_stage(session, rules) -> BracketStage:
    rows: list[BracketRow] = []
    ordered = sorted(
        session.rows, key=lambda r: (r.position is None, r.position or 0)
    )
    leader = _time_of(ordered[0]) if ordered else None

    for row in ordered:
        position = row.position
        progressed = position is not None and position <= GROUP_PROGRESSION_CUTOFF
        rows.append(BracketRow(
            driver_id=row.driver_id,
            driver=row.driver,
            team=row.team,
            position=position,
            time=_time_of(row) if row is ordered[0] else None,
            delta=None if row is ordered[0] else _delta_to(leader, _time_of(row)),
            progressed=progressed,
            is_pole=False,
            points=Decimal(rules.group_progress) if progressed else ZERO,
        ))

    return BracketStage(
        stage=session.stage,
        label=_stage_label(session.stage, session.stage_index),
        rows=rows,
        cut_after=sum(1 for r in rows if r.progressed) or None,
    )


def _duel_stage(session, rules) -> BracketStage:
    rows: list[BracketRow] = []
    ordered = sorted(
        session.rows, key=lambda r: (r.position is None, r.position or 0)
    )
    leader = _time_of(ordered[0]) if ordered else None
    is_final = session.stage == STAGE_FINAL

    for row in ordered:
        won = row.position == 1
        points = ZERO
        if won:
            # The Final winner's cell reads 4, not 1: the duel win plus pole in
            # one figure. Splitting them across a row is fussier than the thing
            # it clarifies, and the POLE marker on the row already explains why
            # this duel paid more than the others.
            points = Decimal(rules.duel_win)
            if is_final:
                points += Decimal(rules.pole)
        rows.append(BracketRow(
            driver_id=row.driver_id,
            driver=row.driver,
            team=row.team,
            position=row.position,
            time=_time_of(row) if won else None,
            delta=None if won else _delta_to(leader, _time_of(row)),
            progressed=won,
            is_pole=won and is_final,
            points=points,
        ))

    return BracketStage(
        stage=session.stage,
        label=_stage_label(session.stage, session.stage_index),
        rows=rows,
    )


def build(stage_results, ruleset) -> list[BracketSection]:
    """The bracket for one round, in reading order.

    `stage_results` is `queries.RoundResults.qualifying` — already sorted into
    bracket order and already carrying its rows. A section with no sessions is
    dropped rather than rendered empty, so a round whose duels have not run yet
    shows its groups and stops, which is exactly what a Saturday afternoon looks
    like.
    """
    rules = ruleset.qualifying
    by_stage: dict[str, list[BracketStage]] = {}

    for session in stage_results:
        if not session.rows:
            continue
        if session.stage == STAGE_GROUP:
            built = _group_stage(session, rules)
        elif session.stage in DUEL_STAGES:
            built = _duel_stage(session, rules)
        else:
            continue
        by_stage.setdefault(session.stage, []).append(built)

    return [
        BracketSection(title=title, stages=by_stage[stage])
        for stage, title in SECTIONS
        if stage in by_stage
    ]


def points_by_driver(sections: list[BracketSection]) -> dict[Any, Decimal]:
    """What the bracket claims each driver earned in qualifying.

    Exists for the test that pins this module to the engine. If these totals
    ever stop matching `engine.score_qualifying`, the structure of the rule has
    been written down twice and the two have disagreed — which is the one
    failure re-deriving from position rather than from stored components can
    cause.
    """
    totals: dict[Any, Decimal] = {}
    for section in sections:
        for stage in section.stages:
            for row in stage.rows:
                totals[row.driver_id] = totals.get(row.driver_id, ZERO) + row.points
    return totals
