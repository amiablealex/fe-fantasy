"""The scoring engine.

Pure functions over plain dicts. Imports nothing from Flask or SQLAlchemy, and
must stay that way: `sim/` exercises this against the backfilled Season 12 data
with no web application and no database, and a test asserts the constraint.

Every score carries its breakdown — which rules fired, for how much, and why.
That is not decoration. SPEC.md §4 makes the points breakdown the core
data-presentation challenge, and §5 stores it so the view is a read rather than
a recomputation. Building the breakdown here means the UI never re-derives it
and never disagrees with the stored total.

Input contract
--------------
A session is a dict::

    {"stage": "group", "stage_index": 1, "rows": [...]}

A row is a dict with the keys this module actually reads::

    {"driver_id": ..., "position": int|None, "grid_position": int|None,
     "status": str|None, "lap_time": str|None}

Deliberately not model instances and not provider dataclasses. The caller adapts
whatever it has into this shape, which is what keeps the engine testable in
isolation and lets the simulation run from a plain SQL read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Sequence

from app.scoring.rules import ScoringRuleset, get_ruleset

# Stage keys, mirroring app.models.calendar. Duplicated rather than imported so
# this module stays free of any dependency that drags in SQLAlchemy.
STAGE_GROUP = "group"
STAGE_QUARTER_FINAL = "quarter_final"
STAGE_SEMI_FINAL = "semi_final"
STAGE_FINAL = "final"
STAGE_RACE = "race"

DUEL_STAGES = (STAGE_QUARTER_FINAL, STAGE_SEMI_FINAL, STAGE_FINAL)

# Top four of each group reach the Duels.
GROUP_PROGRESSION_CUTOFF = 4
PODIUM_CUTOFF = 3
POINTS_FINISH_CUTOFF = 10

# Rule identifiers. Stored against each component so a breakdown stays readable
# after a ruleset version changes the numbers underneath it.
RULE_GROUP_PROGRESS = "group_progress"
RULE_DUEL_WIN = "duel_win"
RULE_POLE = "pole"
RULE_WIN = "race_win"
RULE_PODIUM = "podium"
RULE_POINTS_FINISH = "points_finish"
RULE_FASTEST_LAP = "fastest_lap"
RULE_PLACES_GAINED = "places_gained"
RULE_PLACES_LOST = "places_lost"

_LAP_TIME = re.compile(r"^(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)$")


# -----------------------------------------------------------------------------
# Results
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreComponent:
    """One rule firing for one driver."""

    rule: str
    points: Decimal
    detail: str | None = None


@dataclass(frozen=True)
class DriverRoundScore:
    driver_id: Any
    qualifying: tuple[ScoreComponent, ...] = ()
    race: tuple[ScoreComponent, ...] = ()

    @property
    def qualifying_total(self) -> Decimal:
        return sum((c.points for c in self.qualifying), Decimal(0))

    @property
    def race_total(self) -> Decimal:
        return sum((c.points for c in self.race), Decimal(0))

    @property
    def total(self) -> Decimal:
        return self.qualifying_total + self.race_total

    @property
    def components(self) -> tuple[ScoreComponent, ...]:
        return self.qualifying + self.race

    def fired(self, rule: str) -> bool:
        return any(c.rule == rule for c in self.components)


@dataclass
class RoundScores:
    """Every driver's score for one round, plus anything worth flagging."""

    drivers: dict[Any, DriverRoundScore] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    def total_for(self, driver_id: Any) -> Decimal:
        """An absent driver scores zero. No substitution, no compensation."""
        score = self.drivers.get(driver_id)
        return score.total if score else Decimal(0)

    def score_for(self, driver_id: Any) -> DriverRoundScore:
        return self.drivers.get(driver_id) or DriverRoundScore(driver_id=driver_id)

    @property
    def qualifying_points_distributed(self) -> Decimal:
        return sum((s.qualifying_total for s in self.drivers.values()), Decimal(0))

    @property
    def race_points_distributed(self) -> Decimal:
        return sum((s.race_total for s in self.drivers.values()), Decimal(0))


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def parse_lap_time(value: str | None) -> Decimal | None:
    """Parse a lap time into seconds.

    Comparing the raw strings happens to work today only because every Formula E
    lap is a single-digit minute. That is a property of the current circuits, not
    a guarantee, so parse rather than rely on it.

    Accepts "1:10.945", "70.945" and "1:01:13.217".
    """
    if not value:
        return None
    match = _LAP_TIME.match(str(value).strip())
    if not match:
        return None
    first, second, seconds = match.groups()
    total = Decimal(seconds)
    if second is not None:
        # Three parts: first is hours, second is minutes.
        total += Decimal(second) * 60 + Decimal(first) * 3600
    elif first is not None:
        total += Decimal(first) * 60
    return total


def _rows(session: dict) -> list[dict]:
    return list(session.get("rows") or [])


def _sessions_of(sessions: Iterable[dict], *stages: str) -> list[dict]:
    wanted = set(stages)
    return [s for s in sessions if s.get("stage") in wanted]


def _winner_id(rows: Sequence[dict]) -> Any | None:
    for row in rows:
        if row.get("position") == 1:
            return row.get("driver_id")
    return None


# -----------------------------------------------------------------------------
# Qualifying
# -----------------------------------------------------------------------------


def score_qualifying(
    sessions: Sequence[dict], ruleset: ScoringRuleset | None = None
) -> tuple[dict[Any, list[ScoreComponent]], list[str]]:
    """Score the qualifying bracket.

    Nothing in the payload says who progressed or who won a duel: the group
    sessions give a classification and the duel sessions give two rows each, so
    both facts are derived here.

    Returns (components by driver, issues).
    """
    rules = (ruleset or get_ruleset()).qualifying
    components: dict[Any, list[ScoreComponent]] = {}
    issues: list[str] = []

    def add(driver_id: Any, component: ScoreComponent) -> None:
        components.setdefault(driver_id, []).append(component)

    # --- group stage ---------------------------------------------------------
    groups = _sessions_of(sessions, STAGE_GROUP)
    if not groups:
        issues.append("no group sessions supplied")

    progressed: set[Any] = set()
    for group in groups:
        rows = sorted(
            (r for r in _rows(group) if r.get("position") is not None),
            key=lambda r: r["position"],
        )
        label = f"Group {group.get('stage_index') or '?'}"
        for row in rows[:GROUP_PROGRESSION_CUTOFF]:
            driver_id = row.get("driver_id")
            progressed.add(driver_id)
            add(driver_id, ScoreComponent(
                RULE_GROUP_PROGRESS,
                Decimal(rules.group_progress),
                f"{label} P{row['position']}",
            ))

    # --- duels ---------------------------------------------------------------
    duel_winners: set[Any] = set()
    for stage in DUEL_STAGES:
        for duel in _sessions_of(sessions, stage):
            rows = _rows(duel)
            if len(rows) != 2:
                issues.append(
                    f"{stage} {duel.get('stage_index') or ''}".strip()
                    + f" has {len(rows)} rows, expected 2"
                )
            winner = _winner_id(rows)
            if winner is None:
                issues.append(
                    f"{stage} {duel.get('stage_index') or ''}".strip()
                    + " has no winner in its classification"
                )
                continue
            duel_winners.add(winner)
            index = duel.get("stage_index")
            label = stage.replace("_", " ").title() + (f" {index}" if index else "")
            add(winner, ScoreComponent(RULE_DUEL_WIN, Decimal(rules.duel_win), label))

    # --- pole ----------------------------------------------------------------
    finals = _sessions_of(sessions, STAGE_FINAL)
    if not finals:
        issues.append("no final session supplied; pole not awarded")
    else:
        pole = _winner_id(_rows(finals[0]))
        if pole is None:
            issues.append("final has no winner; pole not awarded")
        else:
            # Pole is the Qual Final winner, never whoever starts P1: a grid
            # penalty moves the pole sitter back while they keep the result.
            add(pole, ScoreComponent(RULE_POLE, Decimal(rules.pole), "Qual Final"))

    # A driver who won a duel without appearing in a group is a data problem
    # worth surfacing rather than silently scoring.
    for winner in duel_winners - progressed:
        issues.append(f"driver {winner} won a duel but did not progress from a group")

    return components, issues


# -----------------------------------------------------------------------------
# Race
# -----------------------------------------------------------------------------


def places_component(
    position: int | None, grid_position: int | None, ruleset: ScoringRuleset | None = None
) -> ScoreComponent | None:
    """Places gained or lost, in steps, capped.

    Returns None when there is nothing to score. A missing or zero grid position
    means a pit-lane start or a data gap: score zero rather than guess a slot.
    """
    rules = (ruleset or get_ruleset()).race
    if position is None or grid_position is None or grid_position <= 0:
        return None

    delta = grid_position - position
    steps = abs(delta) // rules.places_step
    if steps == 0:
        return None

    if delta > 0:
        points = min(steps * rules.places_gained_per_step, rules.places_gained_cap)
        return ScoreComponent(
            RULE_PLACES_GAINED, Decimal(points), f"P{grid_position} to P{position}"
        )

    points = min(steps * rules.places_lost_per_step, rules.places_lost_cap)
    return ScoreComponent(
        RULE_PLACES_LOST, Decimal(-points), f"P{grid_position} to P{position}"
    )


def fastest_lap_driver_ids(rows: Sequence[dict]) -> set[Any]:
    """Whoever set the quickest lap, regardless of finishing position.

    Derived from the minimum lap time and never from `fastest_lap_rank`: that
    field marks the fastest lap among championship-eligible drivers, which
    silently reimposes Formula E's top-ten restriction. This game's point is
    unconditional (SPEC.md §3), and rank disagrees on eight of seventeen
    Season 12 rounds.

    Returns a set because an exact tie, however unlikely, should not be resolved
    by list order.
    """
    timed = [
        (parse_lap_time(row.get("lap_time")), row.get("driver_id"))
        for row in rows
    ]
    timed = [(t, d) for t, d in timed if t is not None]
    if not timed:
        return set()
    quickest = min(t for t, _ in timed)
    return {d for t, d in timed if t == quickest}


def score_race(
    rows: Sequence[dict], ruleset: ScoringRuleset | None = None
) -> tuple[dict[Any, list[ScoreComponent]], list[str]]:
    """Score a race classification.

    Retirements are scored normally. The provider gives them ranked finishing
    positions, so a retiring front-runner takes the full places-lost penalty
    automatically and no separate DNF rule is needed.
    """
    rules = (ruleset or get_ruleset()).race
    components: dict[Any, list[ScoreComponent]] = {}
    issues: list[str] = []

    if not rows:
        return components, ["race classification is empty"]

    fastest = fastest_lap_driver_ids(rows)
    if not fastest:
        issues.append("no lap times in the classification; fastest lap not awarded")
    elif len(fastest) > 1:
        issues.append(f"{len(fastest)} drivers tied on the quickest lap")

    for row in rows:
        driver_id = row.get("driver_id")
        position = row.get("position")
        parts: list[ScoreComponent] = []

        if position is None:
            issues.append(f"driver {driver_id} has no finishing position; scored 0")
            components[driver_id] = parts
            continue

        if position == 1:
            parts.append(ScoreComponent(RULE_WIN, Decimal(rules.win), "P1"))
        if position <= PODIUM_CUTOFF:
            parts.append(ScoreComponent(RULE_PODIUM, Decimal(rules.podium), f"P{position}"))
        if position <= POINTS_FINISH_CUTOFF:
            parts.append(
                ScoreComponent(RULE_POINTS_FINISH, Decimal(rules.points_finish), f"P{position}")
            )
        if driver_id in fastest:
            parts.append(
                ScoreComponent(
                    RULE_FASTEST_LAP, Decimal(rules.fastest_lap), row.get("lap_time")
                )
            )

        grid = row.get("grid_position")
        places = places_component(position, grid, ruleset)
        if places is not None:
            parts.append(places)
        elif grid is None or (isinstance(grid, int) and grid <= 0):
            issues.append(
                f"driver {driver_id} has no grid position; places gained/lost scored 0"
            )

        components[driver_id] = parts

    return components, issues


# -----------------------------------------------------------------------------
# A whole round
# -----------------------------------------------------------------------------


def score_round(
    qualifying_sessions: Sequence[dict],
    race_rows: Sequence[dict],
    ruleset: ScoringRuleset | None = None,
) -> RoundScores:
    """Score one round: qualifying bracket plus race."""
    rules = ruleset or get_ruleset()
    qualifying, quali_issues = score_qualifying(qualifying_sessions, rules)
    race, race_issues = score_race(race_rows, rules)

    scores = RoundScores(issues=quali_issues + race_issues)
    for driver_id in set(qualifying) | set(race):
        scores.drivers[driver_id] = DriverRoundScore(
            driver_id=driver_id,
            qualifying=tuple(qualifying.get(driver_id, ())),
            race=tuple(race.get(driver_id, ())),
        )
    return scores


def score_team(
    scores: RoundScores, driver_ids: Sequence[Any], ruleset: ScoringRuleset | None = None
) -> Decimal:
    """A team scores half the sum of its drivers' round scores.

    Negative places-lost values are included, so a team whose second car has a
    bad afternoon genuinely drags the pick down — which is the judgement the
    team slot is meant to reward.

    Halves are permitted and are not rounded: rounding introduces a bias that
    then needs explaining.
    """
    rules = (ruleset or get_ruleset()).team
    total = sum((scores.total_for(driver_id) for driver_id in driver_ids), Decimal(0))
    return total / rules.divisor
