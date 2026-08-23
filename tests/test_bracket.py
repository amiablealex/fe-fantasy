"""The bracket's figures, pinned to the engine.

`app/meetings/bracket.py` derives what each qualifying stage awarded from a
driver's position plus the round's recorded ruleset, rather than reading it back
from the stored components — `ScoreComponent` records which *rule* fired and not
which session, so attributing a duel win to QF3 rather than SF1 would mean
parsing a detail string written for humans.

That means the structure of the qualifying rule is written down in two places.
Magnitudes cannot drift, because both read the same `ScoringRuleset`. Structure
can, and this is what stops it: every test here asserts the bracket's per-driver
totals equal `engine.score_qualifying`'s own, over the same sessions. If the two
ever disagree the sum breaks here rather than on a phone in December.

Same guard SPEC.md §5 already puts on `transfer_cost` and `scoring_provisional`:
a derived figure is allowed, so long as a test pins it to the recomputation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from app.meetings import bracket
from app.scoring import engine
from app.scoring.rules import get_ruleset

RULESET = get_ruleset()


# -----------------------------------------------------------------------------
# Stubs: the shapes `queries.round_results` produces, without a database.
# -----------------------------------------------------------------------------


@dataclass
class Driver:
    id: Any
    short_label: str


@dataclass
class Row:
    driver_id: Any
    position: int | None
    display_time: str | None = None
    lap_time: str | None = None
    driver: Any = None
    team: Any = None

    def __post_init__(self):
        if self.driver is None:
            self.driver = Driver(self.driver_id, f"D{self.driver_id}")


@dataclass
class Stage:
    stage: str
    stage_index: int | None
    name: str
    rows: list


def _group(index: int, driver_ids: list[int]) -> Stage:
    """Ten drivers, a tenth of a second apart, in order."""
    return Stage(
        stage=engine.STAGE_GROUP,
        stage_index=index,
        name=f"Qual Group {index}",
        rows=[
            Row(d, position=i + 1, display_time=f"1:12.{100 + i * 61:03d}")
            for i, d in enumerate(driver_ids)
        ],
    )


def _duel(stage: str, index: int | None, winner: int, loser: int) -> Stage:
    return Stage(
        stage=stage,
        stage_index=index,
        name=f"Qual {stage} {index or ''}".strip(),
        rows=[
            Row(winner, position=1, display_time="1:11.982"),
            Row(loser, position=2, display_time="1:12.143"),
        ],
    )


def full_bracket() -> list[Stage]:
    """A complete, well-formed round: two groups, four QFs, two SFs, a final.

    Group A sends 1-4, Group B sends 11-14. The knockout runs 1 v 14, 2 v 13,
    3 v 12, 4 v 11, then 1 v 4 and 2 v 3, then 1 v 2.
    """
    return [
        _group(1, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]),
        _group(2, [11, 12, 13, 14, 15, 16, 17, 18, 19, 20]),
        _duel(engine.STAGE_QUARTER_FINAL, 1, 1, 14),
        _duel(engine.STAGE_QUARTER_FINAL, 2, 2, 13),
        _duel(engine.STAGE_QUARTER_FINAL, 3, 3, 12),
        _duel(engine.STAGE_QUARTER_FINAL, 4, 4, 11),
        _duel(engine.STAGE_SEMI_FINAL, 1, 1, 4),
        _duel(engine.STAGE_SEMI_FINAL, 2, 2, 3),
        _duel(engine.STAGE_FINAL, None, 1, 2),
    ]


def _payload(stages: list[Stage]) -> list[dict]:
    """The same sessions in the engine's plain-dict input shape."""
    return [
        {
            "stage": s.stage,
            "stage_index": s.stage_index,
            "rows": [{"driver_id": r.driver_id, "position": r.position} for r in s.rows],
        }
        for s in stages
    ]


def _engine_totals(stages: list[Stage]) -> dict:
    components, _ = engine.score_qualifying(_payload(stages), RULESET)
    return {
        driver_id: sum((c.points for c in parts), Decimal(0))
        for driver_id, parts in components.items()
    }


def _bracket_totals(stages: list[Stage]) -> dict:
    sections = bracket.build(stages, RULESET)
    return {
        driver_id: total
        for driver_id, total in bracket.points_by_driver(sections).items()
        if total
    }


# -----------------------------------------------------------------------------
# The guarantee
# -----------------------------------------------------------------------------


def test_bracket_totals_equal_the_engine_over_a_full_round():
    stages = full_bracket()
    assert _bracket_totals(stages) == _engine_totals(stages)


def test_bracket_totals_equal_the_engine_with_only_the_groups_run():
    """Saturday afternoon: the groups are in, the duels have not happened."""
    stages = full_bracket()[:2]
    assert _bracket_totals(stages) == _engine_totals(stages)


def test_bracket_totals_equal_the_engine_part_way_through_the_duels():
    stages = full_bracket()[:5]
    assert _bracket_totals(stages) == _engine_totals(stages)


def test_the_gradient_matches_the_spec():
    """§3's table: pole 8, lost the final 4, lost a semi 3, lost a QF 2,
    eliminated in the groups 0."""
    totals = _bracket_totals(full_bracket())
    assert totals[1] == 8      # pole
    assert totals[2] == 4      # lost the final
    assert totals[3] == 3      # lost a semi
    assert totals[11] == 2     # lost a quarter-final
    assert 5 not in totals     # eliminated in Group A, P5


# -----------------------------------------------------------------------------
# Shape
# -----------------------------------------------------------------------------


def test_sections_are_in_reading_order_and_empty_ones_are_dropped():
    sections = bracket.build(full_bracket()[:2], RULESET)
    assert [s.title for s in sections] == ["Groups"]

    sections = bracket.build(full_bracket(), RULESET)
    assert [s.title for s in sections] == [
        "Groups", "Quarter-Finals", "Semi-Finals", "Final"
    ]


def test_the_group_cut_falls_after_the_fourth_row():
    groups = bracket.build(full_bracket()[:1], RULESET)[0].stages[0]
    assert groups.cut_after == engine.GROUP_PROGRESSION_CUTOFF
    assert [r.progressed for r in groups.rows][:5] == [True, True, True, True, False]


def test_only_the_leader_carries_an_absolute_time():
    """Everyone below shows a gap. The absolute is noise once the leader's time
    is on the row above."""
    groups = bracket.build(full_bracket()[:1], RULESET)[0].stages[0]
    assert groups.rows[0].time is not None
    assert groups.rows[0].delta is None
    assert all(r.time is None and r.delta is not None for r in groups.rows[1:])


def test_the_delta_is_parsed_not_string_compared():
    """Minute-crossing gaps must still subtract correctly.

    Comparing the raw strings happens to work today only because every Formula E
    lap is a single-digit minute, which is a property of the current circuits.
    """
    stage = Stage(
        stage=engine.STAGE_GROUP, stage_index=1, name="Qual Group 1",
        rows=[
            Row(1, position=1, display_time="59.500"),
            Row(2, position=2, display_time="1:00.500"),
        ],
    )
    rows = bracket.build([stage], RULESET)[0].stages[0].rows
    assert rows[1].delta == "+1.000"


def test_pole_is_marked_only_on_the_final_winner():
    sections = bracket.build(full_bracket(), RULESET)
    poles = [
        r for section in sections for s in section.stages
        for r in s.rows if r.is_pole
    ]
    assert len(poles) == 1
    assert poles[0].driver_id == 1


def test_the_final_winner_carries_the_duel_win_and_the_pole_in_one_figure():
    """4, not 1. Splitting them across a row is fussier than the thing it
    clarifies, and the POLE marker explains why this duel paid more."""
    final = bracket.build(full_bracket(), RULESET)[-1].stages[0]
    expected = RULESET.qualifying.duel_win + RULESET.qualifying.pole
    assert final.rows[0].points == expected


@pytest.mark.parametrize("stages", [[], [Stage(engine.STAGE_GROUP, 1, "x", [])]])
def test_no_sessions_and_no_rows_both_yield_nothing_rather_than_raising(stages):
    assert bracket.build(stages, RULESET) == []
