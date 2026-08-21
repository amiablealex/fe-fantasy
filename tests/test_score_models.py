"""Serialisation tests for the stored scores.

Deliberately free of database fixtures. Everything here constructs a model
instance in memory and reads it back, so the suite runs without the per-test
schema create/drop that costs three minutes on the Pi — and so these tests
still pass if the conftest fixtures are ever renamed.

The schema itself is verified the way SPEC.md §11 prescribes: upgrade, then
autogenerate, and confirm the second pass reports no changes. Constraint
behaviour gets database tests in 5.2, alongside the scoring pass that exercises
it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.score import (
    CONTEST_QUALIFYING,
    CONTEST_RACE,
    SUBJECT_DRIVER,
    SUBJECT_TEAM,
    PickScore,
    RoundScore,
    breakdown_from,
)
from app.models.worker import WorkerRun
from app.scoring.engine import (
    RULE_FASTEST_LAP,
    RULE_PLACES_LOST,
    RULE_POLE,
    RULE_PODIUM,
    ScoreComponent,
)


def _components():
    qualifying = (
        ScoreComponent(RULE_POLE, Decimal(3), "Qual Final"),
    )
    race = (
        ScoreComponent(RULE_PODIUM, Decimal(5), "P3"),
        ScoreComponent(RULE_FASTEST_LAP, Decimal(1), "1:10.945"),
        ScoreComponent(RULE_PLACES_LOST, Decimal(-2), "P1 to P3"),
    )
    return qualifying, race


def test_breakdown_round_trips_through_storage():
    qualifying, race = _components()
    score = RoundScore(
        kind=SUBJECT_DRIVER,
        points=Decimal(7),
        breakdown=breakdown_from(qualifying, race),
        ruleset_version="v1",
    )
    assert score.components() == qualifying + race


def test_contest_is_stored_not_inferred_from_the_rule_name():
    qualifying, race = _components()
    score = RoundScore(breakdown=breakdown_from(qualifying, race))
    assert score.qualifying_components == qualifying
    assert score.race_components == race


def test_negative_points_survive_storage():
    """Places lost is the only rule that can go negative, and it is the one
    that resolves the midfield. A sign lost in serialisation would be silent."""
    _, race = _components()
    score = RoundScore(breakdown=breakdown_from((), race))
    lost = next(c for c in score.components() if c.rule == RULE_PLACES_LOST)
    assert lost.points == Decimal(-2)


def test_halves_survive_storage_exactly():
    """A team scores half the sum of its two cars, so 5.5 is a real score and
    is never rounded (SPEC.md §3). Points are stored as strings rather than
    JSON numbers precisely so this cannot go through a float."""
    score = RoundScore(
        kind=SUBJECT_TEAM,
        points=Decimal("5.5"),
        breakdown=[],
        detail={"cars": [[7, "9"], [11, "2.5"]]},
    )
    assert score.cars == [(7, Decimal("9")), (11, Decimal("2.5"))]
    assert sum(points for _, points in score.cars) / 2 == Decimal("5.75")


def test_empty_breakdown_is_not_an_error():
    """A driver who was on the grid and scored nothing has an empty breakdown,
    which is a different fact from having no row at all."""
    assert RoundScore(breakdown=[]).components() == ()
    assert RoundScore(breakdown=None).components() == ()


def test_subject_id_reads_the_column_the_kind_points_at():
    assert RoundScore(kind=SUBJECT_DRIVER, driver_id=4, team_id=None).subject_id == 4
    assert RoundScore(kind=SUBJECT_TEAM, driver_id=None, team_id=9).subject_id == 9
    assert PickScore(kind=SUBJECT_TEAM, driver_id=None, team_id=9).subject_id == 9


def test_component_json_keeps_a_null_detail():
    score = RoundScore(breakdown=breakdown_from((), (ScoreComponent(RULE_PODIUM, Decimal(5)),)))
    assert score.components()[0].detail is None


def test_contest_constants_partition_the_breakdown():
    qualifying, race = _components()
    stored = breakdown_from(qualifying, race)
    contests = {c["contest"] for c in stored}
    assert contests == {CONTEST_QUALIFYING, CONTEST_RACE}


def test_worker_run_is_running_until_it_finishes():
    started = datetime(2026, 12, 18, 14, 0, tzinfo=timezone.utc)
    run = WorkerRun(job="poll", started_at=started)
    assert run.is_running
    assert run.duration_seconds is None

    run.finished_at = started + timedelta(seconds=12)
    assert not run.is_running
    assert run.duration_seconds == 12
