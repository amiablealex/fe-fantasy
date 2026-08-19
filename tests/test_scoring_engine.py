"""Scoring engine tests.

The five worked examples in SPEC.md §3 are the acceptance cases, and they are
tested first and by name. Everything after them covers a case the spec calls out
in prose but does not tabulate: retirements, pit-lane starts, absent drivers, and
the fastest-lap derivation that Season 12 proved the obvious field gets wrong.

No database and no app fixture anywhere in this file. That is the point.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.scoring.engine import (
    RULE_DUEL_WIN,
    RULE_FASTEST_LAP,
    RULE_GROUP_PROGRESS,
    RULE_PLACES_GAINED,
    RULE_PLACES_LOST,
    RULE_POINTS_FINISH,
    RULE_PODIUM,
    RULE_POLE,
    RULE_WIN,
    STAGE_FINAL,
    STAGE_GROUP,
    STAGE_QUARTER_FINAL,
    STAGE_SEMI_FINAL,
    fastest_lap_driver_ids,
    parse_lap_time,
    places_component,
    score_qualifying,
    score_race,
    score_round,
    score_team,
)


# -----------------------------------------------------------------------------
# Builders
# -----------------------------------------------------------------------------


def group(index: int, driver_ids):
    return {
        "stage": STAGE_GROUP,
        "stage_index": index,
        "rows": [
            {"driver_id": d, "position": p} for p, d in enumerate(driver_ids, start=1)
        ],
    }


def duel(stage: str, index, winner, loser):
    return {
        "stage": stage,
        "stage_index": index,
        "rows": [
            {"driver_id": winner, "position": 1},
            {"driver_id": loser, "position": 2},
        ],
    }


def full_bracket(order):
    """A complete nine-session bracket.

    `order` is the eight duel qualifiers, best first: order[0] takes pole.
    Groups are padded to ten drivers each so the progression cutoff is real.
    """
    a = list(order[0::2]) + [f"gA{i}" for i in range(6)]
    b = list(order[1::2]) + [f"gB{i}" for i in range(6)]

    sessions = [group(1, a), group(2, b)]
    # Quarter-finals: 1v8, 2v7, 3v6, 4v5, seeded so `order` wins through.
    pairs = [(order[0], order[7]), (order[1], order[6]),
             (order[2], order[5]), (order[3], order[4])]
    for i, (w, l) in enumerate(pairs, start=1):
        sessions.append(duel(STAGE_QUARTER_FINAL, i, w, l))
    sessions.append(duel(STAGE_SEMI_FINAL, 1, order[0], order[3]))
    sessions.append(duel(STAGE_SEMI_FINAL, 2, order[1], order[2]))
    sessions.append(duel(STAGE_FINAL, None, order[0], order[1]))
    return sessions


def race_row(driver_id, position, grid, *, lap="1:15.000", status=None):
    return {
        "driver_id": driver_id,
        "position": position,
        "grid_position": grid,
        "status": status,
        "lap_time": lap,
    }


# -----------------------------------------------------------------------------
# The five worked examples from SPEC.md §3
# -----------------------------------------------------------------------------


def test_worked_example_pole_wins_from_p1_sets_fastest_lap():
    """Quali 8 + win 5 + podium 5 + points 2 + FL 1 + places 0 = 21."""
    sessions = full_bracket(["hero"] + [f"d{i}" for i in range(1, 8)])
    rows = [race_row("hero", 1, 1, lap="1:10.000")]
    rows += [race_row(f"d{i}", i + 1, i + 1) for i in range(1, 8)]

    scores = score_round(sessions, rows)
    hero = scores.score_for("hero")

    assert hero.qualifying_total == Decimal(8)
    assert hero.race_total == Decimal(13)
    assert hero.total == Decimal(21)
    assert not hero.fired(RULE_PLACES_GAINED)
    assert not hero.fired(RULE_PLACES_LOST)


def test_worked_example_wins_from_p6_after_a_group_exit():
    """5 + 5 + 2 + places gained 2 = 14, with nothing from qualifying."""
    sessions = full_bracket([f"d{i}" for i in range(1, 9)])
    rows = [race_row("hero", 1, 6, lap="1:20.000")]
    rows += [race_row(f"d{i}", i + 1, i) for i in range(1, 9)]

    scores = score_round(sessions, rows)
    hero = scores.score_for("hero")

    assert hero.qualifying_total == Decimal(0)
    assert hero.total == Decimal(14)
    assert hero.fired(RULE_PLACES_GAINED)


def test_worked_example_pole_then_retires_classified_p18():
    """Quali 8 + places lost -4 = 4."""
    sessions = full_bracket(["hero"] + [f"d{i}" for i in range(1, 8)])
    rows = [race_row("hero", 18, 1, status="DNF", lap="1:30.000")]
    rows += [race_row(f"d{i}", i, i + 1, lap="1:15.000") for i in range(1, 18)]

    scores = score_round(sessions, rows)
    hero = scores.score_for("hero")

    assert hero.qualifying_total == Decimal(8)
    assert hero.race_total == Decimal(-4)
    assert hero.total == Decimal(4)


def test_worked_example_p4_qualifier_finishes_p3():
    """Quali 3 (group 2 + one duel win) + podium 5 + points 2 = 10."""
    order = ["a", "b", "c", "hero", "e", "f", "g", "h"]
    sessions = full_bracket(order)
    rows = [race_row("hero", 3, 4, lap="1:20.000")]
    rows += [race_row(d, i, i, lap="1:15.000")
             for i, d in enumerate(["a", "b"], start=1)]

    scores = score_round(sessions, rows)
    hero = scores.score_for("hero")

    assert hero.qualifying_total == Decimal(3)
    assert hero.total == Decimal(10)


def test_worked_example_p20_qualifier_finishes_p11():
    """Places gained +2, and nothing else."""
    sessions = full_bracket([f"d{i}" for i in range(1, 9)])
    rows = [race_row("hero", 11, 20, lap="1:30.000")]
    rows += [race_row(f"d{i}", i, i, lap="1:15.000") for i in range(1, 11)]

    scores = score_round(sessions, rows)
    hero = scores.score_for("hero")

    assert hero.total == Decimal(2)
    assert [c.rule for c in hero.components] == [RULE_PLACES_GAINED]


# -----------------------------------------------------------------------------
# Qualifying
# -----------------------------------------------------------------------------


def test_the_qualifying_gradient_matches_the_spec():
    order = ["pole", "lost_final", "lost_semi_a", "lost_semi_b",
             "qf1", "qf2", "qf3", "qf4"]
    components, issues = score_qualifying(full_bracket(order))
    assert issues == []

    def total(driver_id):
        return sum((c.points for c in components.get(driver_id, [])), Decimal(0))

    assert total("pole") == Decimal(8)
    assert total("lost_final") == Decimal(4)
    assert total("lost_semi_a") == Decimal(3)
    assert total("qf4") == Decimal(2)
    assert total("gA0") == Decimal(0)


def test_twenty_six_qualifying_points_are_distributed_per_round():
    components, _ = score_qualifying(full_bracket([f"d{i}" for i in range(8)]))
    total = sum(
        (c.points for parts in components.values() for c in parts), Decimal(0)
    )
    assert total == Decimal(26)


def test_only_the_top_four_of_each_group_progress():
    sessions = full_bracket([f"d{i}" for i in range(8)])
    components, _ = score_qualifying(sessions)
    progressed = [d for d, parts in components.items()
                  if any(c.rule == RULE_GROUP_PROGRESS for c in parts)]
    assert len(progressed) == 8


def test_pole_comes_from_the_final_not_the_grid():
    """A grid penalty moves the pole sitter back while they keep the result."""
    sessions = full_bracket(["pole"] + [f"d{i}" for i in range(1, 8)])
    components, _ = score_qualifying(sessions)
    assert any(c.rule == RULE_POLE for c in components["pole"])
    # Nothing in score_qualifying reads a grid position at all.
    assert all(
        c.rule != RULE_POLE
        for driver, parts in components.items() if driver != "pole"
        for c in parts
    )


def test_winning_the_final_counts_as_a_duel_win_and_pole():
    sessions = full_bracket(["pole"] + [f"d{i}" for i in range(1, 8)])
    components, _ = score_qualifying(sessions)
    parts = components["pole"]
    assert len([c for c in parts if c.rule == RULE_DUEL_WIN]) == 3
    assert len([c for c in parts if c.rule == RULE_POLE]) == 1


def test_a_missing_final_is_reported_rather_than_scored():
    sessions = [s for s in full_bracket([f"d{i}" for i in range(8)])
                if s["stage"] != STAGE_FINAL]
    components, issues = score_qualifying(sessions)
    assert any("final" in i for i in issues)
    assert all(c.rule != RULE_POLE for parts in components.values() for c in parts)


def test_a_duel_with_the_wrong_row_count_is_flagged():
    sessions = full_bracket([f"d{i}" for i in range(8)])
    for session in sessions:
        if session["stage"] == STAGE_SEMI_FINAL:
            session["rows"] = session["rows"][:1]
            break
    _, issues = score_qualifying(sessions)
    assert any("expected 2" in i for i in issues)


# -----------------------------------------------------------------------------
# Places gained and lost
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("grid,finish,expected", [
    (10, 10, 0),      # no change
    (10, 6, 0),       # four places: under the step
    (10, 5, 2),       # five: one step
    (10, 1, 2),       # nine: still one step
    (20, 10, 4),      # ten: two steps
    (20, 1, 4),       # nineteen: capped
    (5, 10, -2),
    (1, 11, -4),
    (1, 18, -4),      # capped
])
def test_places_steps_and_caps(grid, finish, expected):
    component = places_component(finish, grid)
    if expected == 0:
        assert component is None
    else:
        assert component.points == Decimal(expected)


def test_the_asymmetry_is_structural():
    """A front-row qualifier has no upside and full downside exposure; a
    back-row qualifier the reverse. That tension is the point."""
    assert places_component(1, 1) is None
    assert places_component(20, 1).points == Decimal(-4)
    assert places_component(1, 20).points == Decimal(4)


def test_a_pit_lane_start_scores_no_places_and_is_reported():
    rows = [race_row("hero", 15, 0), race_row("other", 1, 1)]
    components, issues = score_race(rows)
    assert not any(c.rule in (RULE_PLACES_GAINED, RULE_PLACES_LOST)
                   for c in components["hero"])
    assert any("no grid position" in i for i in issues)


def test_a_null_grid_position_is_never_guessed():
    assert places_component(5, None) is None
    assert places_component(5, 0) is None


# -----------------------------------------------------------------------------
# Fastest lap
# -----------------------------------------------------------------------------


def test_fastest_lap_comes_from_lap_time_not_from_rank():
    """Season 12's finding: `fastest_lap_rank` marks the quickest lap among
    top-ten finishers, so a P19 driver who set the genuinely quickest lap is
    invisible to it. This game's point is unconditional."""
    rows = [
        race_row("winner", 1, 1, lap="1:11.566"),
        race_row("eligible", 2, 2, lap="1:11.394"),
        race_row("backmarker", 19, 20, lap="1:10.945"),
    ]
    # The provider would mark `eligible` here; the engine must not care.
    rows[1]["fastest_lap_rank"] = 1

    assert fastest_lap_driver_ids(rows) == {"backmarker"}
    components, _ = score_race(rows)
    assert any(c.rule == RULE_FASTEST_LAP for c in components["backmarker"])
    assert not any(c.rule == RULE_FASTEST_LAP for c in components["eligible"])


def test_the_fastest_lap_point_is_unconditional_on_position():
    rows = [race_row("winner", 1, 1, lap="1:20.000"),
            race_row("last", 20, 20, lap="1:10.000")]
    components, _ = score_race(rows)
    last = components["last"]
    assert [c.rule for c in last] == [RULE_PLACES_GAINED, RULE_FASTEST_LAP] or \
           sorted(c.rule for c in last) == sorted([RULE_FASTEST_LAP])


def test_lap_times_are_parsed_not_string_compared():
    """String comparison works today only because every lap is a single-digit
    minute. That is a property of the circuits, not a guarantee."""
    assert parse_lap_time("1:10.945") == Decimal("70.945")
    assert parse_lap_time("59.500") == Decimal("59.500")
    assert parse_lap_time("1:01:13.217") == Decimal("3673.217")
    assert parse_lap_time(None) is None
    assert parse_lap_time("nonsense") is None

    # The case string comparison gets wrong: "10:00.000" sorts before "9:00.000".
    assert parse_lap_time("10:00.000") > parse_lap_time("9:00.000")


def test_a_race_with_no_lap_times_awards_no_fastest_lap():
    rows = [race_row("a", 1, 1, lap=None), race_row("b", 2, 2, lap=None)]
    components, issues = score_race(rows)
    assert not any(c.rule == RULE_FASTEST_LAP
                   for parts in components.values() for c in parts)
    assert any("fastest lap not awarded" in i for i in issues)


def test_an_exact_tie_on_the_quickest_lap_is_reported():
    rows = [race_row("a", 1, 1, lap="1:10.000"), race_row("b", 2, 2, lap="1:10.000")]
    assert fastest_lap_driver_ids(rows) == {"a", "b"}
    _, issues = score_race(rows)
    assert any("tied" in i for i in issues)


# -----------------------------------------------------------------------------
# Race rules stacking
# -----------------------------------------------------------------------------


def test_a_win_stacks_win_podium_and_points():
    rows = [race_row("hero", 1, 1, lap="1:20.000"), race_row("x", 2, 2)]
    components, _ = score_race(rows)
    fired = {c.rule for c in components["hero"]}
    assert fired == {RULE_WIN, RULE_PODIUM, RULE_POINTS_FINISH}
    assert sum((c.points for c in components["hero"]), Decimal(0)) == Decimal(12)


def test_the_race_ceiling_is_seventeen():
    rows = [race_row("hero", 1, 20, lap="1:10.000")]
    rows += [race_row(f"d{i}", i, i, lap="1:20.000") for i in range(2, 21)]
    components, _ = score_race(rows)
    assert sum((c.points for c in components["hero"]), Decimal(0)) == Decimal(17)


def test_the_midfield_is_resolved_only_by_places():
    """Without places gained/lost, P4 through P10 would score identically. This
    is the reason the rule ships in v1."""
    # Distinct lap times, quickest at the front, so the fastest-lap point does
    # not land in the band under test.
    rows = [race_row(f"d{p}", p, p, lap=f"1:{10 + p}.500") for p in range(1, 21)]
    components, _ = score_race(rows)
    flat = {p: sum((c.points for c in components[f"d{p}"]), Decimal(0))
            for p in range(4, 11)}
    assert set(flat.values()) == {Decimal(2)}, (
        "P4 through P10 must be indistinguishable without places gained/lost"
    )

    moved = [race_row("gainer", 4, 14, lap="1:25.000")]
    moved += [race_row(f"d{p}", p, p, lap=f"1:{10 + p}.500")
              for p in range(1, 21) if p != 4]
    gained, _ = score_race(moved)
    # Points finish 2 + two steps gained 4. Nothing else fires at P4.
    assert sum((c.points for c in gained["gainer"]), Decimal(0)) == Decimal(6)


def test_a_retirement_is_scored_from_its_classification():
    """Retirements receive ranked positions, so places lost punishes them
    automatically and no separate DNF rule is needed."""
    rows = [race_row("dnf", 20, 2, status="DNF", lap="1:30.000")]
    rows += [race_row(f"d{p}", p, p + 2, lap="1:21.000") for p in range(1, 20)]
    components, _ = score_race(rows)
    assert sum((c.points for c in components["dnf"]), Decimal(0)) == Decimal(-4)


def test_an_empty_classification_is_reported():
    components, issues = score_race([])
    assert components == {}
    assert issues == ["race classification is empty"]


# -----------------------------------------------------------------------------
# Rounds, absent drivers, teams
# -----------------------------------------------------------------------------


def test_an_absent_driver_scores_zero():
    """No substitution, no compensation."""
    scores = score_round(full_bracket([f"d{i}" for i in range(8)]),
                         [race_row("d0", 1, 1)])
    assert scores.total_for("someone-who-did-not-race") == Decimal(0)
    assert scores.score_for("someone-who-did-not-race").components == ()


def test_team_scores_half_the_sum_of_its_drivers():
    sessions = full_bracket(["a", "b"] + [f"d{i}" for i in range(6)])
    rows = [race_row("a", 1, 1, lap="1:10.000"), race_row("b", 5, 5, lap="1:20.000")]
    scores = score_round(sessions, rows)

    expected = (scores.total_for("a") + scores.total_for("b")) / 2
    assert score_team(scores, ["a", "b"]) == expected


def test_team_scoring_permits_halves_and_does_not_round():
    sessions = full_bracket([f"d{i}" for i in range(8)])
    rows = [race_row("d0", 1, 1, lap="1:10.000"), race_row("d1", 11, 11)]
    scores = score_round(sessions, rows)
    total = score_team(scores, ["d0", "d1"])
    assert total == (scores.total_for("d0") + scores.total_for("d1")) / 2
    assert total % 1 in (Decimal("0"), Decimal("0.5"))


def test_team_scoring_includes_negative_places_lost():
    """A team whose second car has a bad afternoon genuinely drags the pick
    down, which is the judgement the team slot rewards."""
    sessions = full_bracket([f"d{i}" for i in range(8)])
    rows = [race_row("star", 1, 1, lap="1:10.000"),
            race_row("dud", 20, 2, lap="1:30.000")]
    scores = score_round(sessions, rows)
    assert scores.total_for("dud") < 0
    assert score_team(scores, ["star", "dud"]) < scores.total_for("star") / 2


def test_a_team_with_an_absent_driver_scores_only_the_one_who_raced():
    sessions = full_bracket([f"d{i}" for i in range(8)])
    scores = score_round(sessions, [race_row("d0", 1, 1, lap="1:10.000")])
    assert score_team(scores, ["d0", "missing"]) == scores.total_for("d0") / 2


def test_round_totals_separate_qualifying_from_race():
    sessions = full_bracket(["hero"] + [f"d{i}" for i in range(1, 8)])
    rows = [race_row("hero", 1, 1, lap="1:10.000")]
    scores = score_round(sessions, rows)
    assert scores.qualifying_points_distributed == Decimal(26)
    assert scores.race_points_distributed == scores.score_for("hero").race_total


def test_the_breakdown_names_every_rule_that_fired():
    """SPEC.md §4 makes this the core presentation challenge, so it has to be
    available without recomputation."""
    sessions = full_bracket(["hero"] + [f"d{i}" for i in range(1, 8)])
    rows = [race_row("hero", 1, 6, lap="1:10.000")]
    hero = score_round(sessions, rows).score_for("hero")

    rules = [c.rule for c in hero.components]
    assert RULE_GROUP_PROGRESS in rules
    assert RULE_POLE in rules
    assert RULE_WIN in rules
    assert RULE_PLACES_GAINED in rules
    assert all(c.detail for c in hero.components if c.rule != RULE_FASTEST_LAP)
    assert sum((c.points for c in hero.components), Decimal(0)) == hero.total


def test_the_engine_imports_nothing_from_flask_or_sqlalchemy():
    """SPEC.md §12: sim/ must run this without a web app or a database.

    Parsed rather than grepped: the docstrings legitimately mention both names,
    and a substring check would either fail on prose or be too loose to mean
    anything.
    """
    import ast
    import inspect

    from app.scoring import engine, lineups, rules

    forbidden = ("flask", "sqlalchemy", "psycopg")

    for module in (engine, lineups, rules):
        tree = ast.parse(inspect.getsource(module))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")

        for name in imported:
            root = name.split(".")[0].lower()
            assert root not in forbidden, (
                f"{module.__name__} imports {name}, which would stop sim/ "
                "running without a database"
            )
