"""Results ingestion tests."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.ingest.checks import (
    FIRST_QUALIFYING_POINTS_SEASON_YEAR,
    expected_championship_points,
    verify_championship_points,
)
from app.ingest.results import (
    INGESTED_STAGES,
    ResultsReport,
    backfill_season,
    sync_session_results,
)
from app.ingest.season import sync_season
from app.models.calendar import (
    STAGE_FINAL,
    STAGE_GROUP,
    STAGE_OTHER,
    STAGE_PRACTICE,
    STAGE_RACE,
    Round,
    Season,
    Session,
)
from app.models.grid import Driver
from app.models.result import Result
from app.providers.base import DriverRef, ResultRow, TeamRef
from app.providers.errors import ProviderTransientError

from tests.test_sync_season import FakeProvider, make_event, make_location

RACE_POINTS = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]


def make_result_row(
    position, *, grid=None, points=None, fl=False, dnf=False,
    driver_id=None, team_id="t1",
):
    return ResultRow(
        id=f"res-{driver_id or position}-{position}",
        position=position,
        grid_position=grid if grid is not None else position,
        driver=DriverRef(
            id=driver_id or f"d{position}", first_name="F", last_name=f"L{position}",
            code=None, number=position,
        ),
        team=TeamRef(id=team_id, name="TEAM", short_name="TM", color="000000"),
        status="DNF" if dnf else None,
        points=Decimal(str(points)) if points is not None else None,
        fastest_lap_rank=1 if fl else None,
        car_number=position,
        lap_time="1:15.300",
        display_time="1:01:13.217",
    )


def make_race_classification(n=20, *, fl_position=3):
    """A well-formed race payload whose points match the real distribution."""
    rows = []
    for position in range(1, n + 1):
        base = RACE_POINTS[position - 1] if position <= 10 else 0
        if position == 1:
            base += 3  # the pole sitter starts P1
        if position == fl_position:
            base += 1
        rows.append(make_result_row(position, points=base, fl=(position == fl_position)))
    return rows


class ResultsProviderStub(FakeProvider):
    """Adds result serving to the calendar fake."""

    def __init__(self, events, payloads, year=2026, fail_on=None):
        super().__init__(events, year=year)
        self.payloads = payloads          # session provider id -> rows
        self.fail_on = fail_on or set()
        self.calls: list[tuple[str, str]] = []

    def get_results(self, event_id, session_id):
        self.calls.append((event_id, session_id))
        if session_id in self.fail_on:
            raise ProviderTransientError("upstream wobble")
        return list(self.payloads.get(session_id, []))


@pytest.fixture()
def synced(db):
    """One single-header meeting, fully synced, with no results yet."""
    events = [make_event("e1", date(2026, 7, 25), make_location())]
    sync_season(FakeProvider(events), 2026)
    return events


def _session(db, stage, ordinal=None):
    stmt = select(Session).where(Session.stage == stage).order_by(Session.ordinal)
    return db.session.scalars(stmt).first()


# -----------------------------------------------------------------------------
# What gets fetched
# -----------------------------------------------------------------------------


def test_only_qualifying_and_race_stages_are_ingested():
    assert STAGE_RACE in INGESTED_STAGES
    assert STAGE_GROUP in INGESTED_STAGES
    assert STAGE_FINAL in INGESTED_STAGES
    # Rookie Free Practice arrives as `other` and is full of drivers who are not
    # on the grid.
    assert STAGE_PRACTICE not in INGESTED_STAGES
    assert STAGE_OTHER not in INGESTED_STAGES


def test_practice_and_other_sessions_are_never_requested(db, synced):
    events = [make_event("e1", date(2026, 7, 25), make_location(), include_other=True)]
    sync_season(FakeProvider(events), 2026)

    provider = ResultsProviderStub(events, {})
    backfill_season(provider, 2026)

    requested = {sid for _, sid in provider.calls}
    skipped = db.session.scalars(
        select(Session).where(Session.stage.in_([STAGE_PRACTICE, STAGE_OTHER]))
    ).all()
    assert skipped
    for session_row in skipped:
        assert session_row.provider_session_id not in requested


def test_a_session_that_is_not_complete_is_not_requested(db, synced):
    race = _session(db, STAGE_RACE)
    race.status = "scheduled"
    db.session.commit()

    provider = ResultsProviderStub(synced, {race.provider_session_id: make_race_classification()})
    season = db.session.scalar(select(Season))
    report = ResultsReport(season_year=2026)
    sync_session_results(provider, race, season, report)

    assert provider.calls == []
    assert report.sessions_skipped_not_complete == 1


# -----------------------------------------------------------------------------
# Writing rows
# -----------------------------------------------------------------------------


def test_race_results_are_written(db, synced):
    race = _session(db, STAGE_RACE)
    provider = ResultsProviderStub(
        synced, {race.provider_session_id: make_race_classification()}
    )
    report = backfill_season(provider, 2026)

    assert report.ok
    rows = db.session.scalars(
        select(Result).where(Result.session_id == race.id).order_by(Result.position)
    ).all()
    assert len(rows) == 20
    assert rows[0].position == 1
    assert rows[0].points == Decimal("28")   # 25 + 3 for pole
    assert [r for r in rows if r.set_fastest_lap][0].position == 3


def test_ingestion_stamps_the_session(db, synced):
    race = _session(db, STAGE_RACE)
    provider = ResultsProviderStub(
        synced, {race.provider_session_id: make_race_classification()}
    )
    backfill_season(provider, 2026)

    db.session.expire_all()
    race = _session(db, STAGE_RACE)
    assert race.results_ingested_at is not None


def test_backfill_is_idempotent(db, synced):
    race = _session(db, STAGE_RACE)
    payloads = {race.provider_session_id: make_race_classification()}

    first = backfill_season(ResultsProviderStub(synced, payloads), 2026)
    second = backfill_season(ResultsProviderStub(synced, payloads), 2026)

    assert first.rows_created == 20
    assert second.rows_created == 0
    assert second.sessions_skipped_already_ingested >= 1
    assert len(db.session.scalars(select(Result)).all()) == 20


def test_force_reingests_and_updates_rather_than_duplicating(db, synced):
    race = _session(db, STAGE_RACE)
    payloads = {race.provider_session_id: make_race_classification()}
    backfill_season(ResultsProviderStub(synced, payloads), 2026)

    # A corrected classification: the winner is disqualified to last.
    corrected = make_race_classification()
    corrected[0] = make_result_row(20, grid=1, points=0, driver_id="d1")
    payloads[race.provider_session_id] = corrected

    report = backfill_season(ResultsProviderStub(synced, payloads), 2026, force=True)

    assert report.rows_created == 0
    assert report.rows_updated == 20
    assert len(db.session.scalars(select(Result)).all()) == 20

    d1 = db.session.scalar(select(Driver).where(Driver.provider_driver_id == "d1"))
    row = db.session.scalar(select(Result).where(Result.driver_id == d1.id))
    assert row.position == 20


def test_a_driver_absent_from_the_standings_is_created(db, synced):
    """A one-off reserve appears in results before any seat entry exists. This
    is why results reference drivers directly."""
    race = _session(db, STAGE_RACE)
    rows = make_race_classification(19)
    rows.append(make_result_row(20, points=0, driver_id="reserve-1"))

    provider = ResultsProviderStub(synced, {race.provider_session_id: rows})
    report = backfill_season(provider, 2026)

    assert report.drivers_created >= 1
    reserve = db.session.scalar(
        select(Driver).where(Driver.provider_driver_id == "reserve-1")
    )
    assert reserve is not None
    assert db.session.scalar(
        select(Result).where(Result.driver_id == reserve.id)
    ) is not None


def test_qualifying_rows_without_points_or_status_are_stored(db, synced):
    """Those keys are absent from duel payloads, not null."""
    final = _session(db, STAGE_FINAL)
    duel = [
        ResultRow(id="q1", position=1, grid_position=None,
                  driver=DriverRef(id="d1", first_name="A", last_name="B",
                                   code=None, number=1),
                  team=TeamRef(id="t1", name="TEAM", short_name="TM", color="000000"),
                  status=None, points=None, fastest_lap_rank=None, car_number=1,
                  lap_time=None, display_time="1:12.341"),
        ResultRow(id="q2", position=2, grid_position=None,
                  driver=DriverRef(id="d2", first_name="C", last_name="D",
                                   code=None, number=2),
                  team=TeamRef(id="t2", name="TEAM2", short_name="T2", color="000000"),
                  status=None, points=None, fastest_lap_rank=None, car_number=2,
                  lap_time=None, display_time="1:12.500"),
    ]
    provider = ResultsProviderStub(synced, {final.provider_session_id: duel})
    report = backfill_season(provider, 2026)

    assert report.ok
    rows = db.session.scalars(
        select(Result).where(Result.session_id == final.id)
    ).all()
    assert len(rows) == 2
    assert all(r.points is None and r.status is None for r in rows)
    assert rows[0].display_time == "1:12.341"


def test_a_missing_grid_position_is_reported(db, synced):
    """Places gained/lost scores 0 there rather than guessing."""
    race = _session(db, STAGE_RACE)
    rows = make_race_classification()
    rows[14] = make_result_row(15, grid=0, points=0)

    provider = ResultsProviderStub(synced, {race.provider_session_id: rows})
    report = backfill_season(provider, 2026)

    assert any("no grid position" in w for w in report.warnings)


# -----------------------------------------------------------------------------
# Failure isolation
# -----------------------------------------------------------------------------


def test_one_failing_session_does_not_abandon_the_round(db, synced):
    race = _session(db, STAGE_RACE)
    group_a = _session(db, STAGE_GROUP)
    payloads = {race.provider_session_id: make_race_classification()}

    provider = ResultsProviderStub(
        synced, payloads, fail_on={group_a.provider_session_id}
    )
    report = backfill_season(provider, 2026)

    assert not report.ok
    assert len(report.errors) == 1
    # The race still landed.
    assert len(db.session.scalars(
        select(Result).where(Result.session_id == race.id)
    ).all()) == 20


def test_a_failed_session_is_not_stamped_and_retries_next_run(db, synced):
    group_a = _session(db, STAGE_GROUP)
    provider = ResultsProviderStub(synced, {}, fail_on={group_a.provider_session_id})
    backfill_season(provider, 2026)

    db.session.expire_all()
    group_a = _session(db, STAGE_GROUP)
    assert group_a.results_ingested_at is None


def test_a_completed_session_returning_nothing_is_flagged(db, synced):
    race = _session(db, STAGE_RACE)
    provider = ResultsProviderStub(synced, {race.provider_session_id: []})
    report = backfill_season(provider, 2026)
    assert any("returned no rows" in w for w in report.warnings)


def test_backfill_without_a_synced_season_says_so(db):
    report = backfill_season(ResultsProviderStub([], {}), 2026)
    assert not report.ok
    assert "sync-season" in report.errors[0]


def test_backfill_can_target_specific_rounds(db):
    london = make_location()
    events = [make_event("e1", date(2026, 7, 25), london),
              make_event("e2", date(2026, 7, 26), london)]
    sync_season(FakeProvider(events), 2026)

    races = db.session.scalars(
        select(Session).where(Session.stage == STAGE_RACE).order_by(Session.id)
    ).all()
    payloads = {s.provider_session_id: make_race_classification() for s in races}

    provider = ResultsProviderStub(events, payloads)
    backfill_season(provider, 2026, round_numbers=[2])

    round_two = db.session.scalar(select(Round).where(Round.round_number == 2))
    round_one = db.session.scalar(select(Round).where(Round.round_number == 1))
    ingested = db.session.scalars(
        select(Session).where(Session.results_ingested_at.isnot(None))
    ).all()
    assert {s.round_id for s in ingested} == {round_two.id}
    assert round_one.id not in {s.round_id for s in ingested}


# -----------------------------------------------------------------------------
# Championship points sanity check
# -----------------------------------------------------------------------------


def test_expected_points_include_the_pole_bonus():
    winner = make_result_row(1, grid=1, points=28)
    assert expected_championship_points(winner, pole_driver_id="d1") == Decimal(28)
    # Starting P1 is not pole: a grid penalty moves the pole sitter back while
    # they keep the point. Sao Paulo 2025 is the case in point.
    assert expected_championship_points(winner) == Decimal(25)


def test_expected_points_include_fastest_lap_only_inside_the_top_ten():
    """Formula E's own rule. The fantasy point deliberately differs."""
    third_with_fl = make_result_row(3, grid=3, fl=True)
    fifteenth_with_fl = make_result_row(15, grid=15, fl=True)
    assert expected_championship_points(third_with_fl) == Decimal(16)
    assert expected_championship_points(fifteenth_with_fl) == Decimal(0)


def test_a_pole_sitter_who_retires_still_scores_the_pole_bonus():
    retired = make_result_row(18, grid=1, dnf=True)
    assert expected_championship_points(retired, pole_driver_id="d18") == Decimal(3)


def test_an_unknown_pole_sitter_accepts_either_total():
    """Qualifying may not be ingested yet, so a row could legitimately carry
    the pole bonus. Better to accept both than invent a complaint."""
    rows = make_race_classification()
    assert verify_championship_points(2026, STAGE_RACE, rows) == []
    assert verify_championship_points(2026, STAGE_RACE, rows, pole_driver_id="d1") == []


def test_a_well_formed_payload_reports_nothing():
    assert verify_championship_points(2026, STAGE_RACE, make_race_classification()) == []


def test_a_single_mismatch_is_reported():
    rows = make_race_classification()
    rows[5] = make_result_row(6, points=99)
    problems = verify_championship_points(2026, STAGE_RACE, rows)
    assert len(problems) == 1
    assert "expected 8" in problems[0]


def test_a_field_wide_mismatch_says_the_expectation_is_wrong():
    """Twenty individual complaints would be noise; one about the assumption is
    the useful message."""
    rows = [make_result_row(p, points=p) for p in range(1, 21)]
    problems = verify_championship_points(2026, STAGE_RACE, rows)
    assert len(problems) == 1
    assert "expectation may need revising" in problems[0]


def test_the_check_is_skipped_from_season_13():
    """Qualifying now awards championship points on a sliding scale, so the
    Season 12 expectation would fail on every round."""
    rows = make_race_classification()
    rows[0] = make_result_row(1, grid=1, points=32)
    assert verify_championship_points(
        FIRST_QUALIFYING_POINTS_SEASON_YEAR, STAGE_RACE, rows
    ) == []


def test_the_check_ignores_qualifying_sessions():
    assert verify_championship_points(2026, STAGE_FINAL, []) == []


def test_a_race_with_no_points_at_all_is_flagged():
    rows = [make_result_row(p) for p in range(1, 21)]
    problems = verify_championship_points(2026, STAGE_RACE, rows)
    assert problems and "may be incomplete" in problems[0]
