"""The poller, without a network.

The provider is faked. What is being tested is the part that decides *whether*
to call — the window, the cadence, the ceiling — because that is the part that
either keeps the worker inside a 7,500-a-month free tier or does not, and it is
the part that cannot be checked against a live weekend until December.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.extensions import db as _db
from app.models.calendar import (
    SESSION_STATUS_SCHEDULED,
    SESSION_TYPE_RACE,
    STAGE_PRACTICE,
    STAGE_RACE,
    Session,
)
from app.models.result import Result
from app.models.worker import JOB_POLL, JOB_SEASON_SYNC, WorkerRun
from worker import jobs
from worker.runs import Run

NOW = datetime(2026, 12, 19, 18, 0, tzinfo=timezone.utc)


# -----------------------------------------------------------------------------
# A provider that answers from a script
# -----------------------------------------------------------------------------


class FakeProvider:
    """Returns whatever it was told to, and counts every call.

    `answers` maps a provider session id to either a list of rows or an
    exception to raise — the two shapes a session that has not been published
    might come back as, and the poller has to treat them identically.
    """

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = 0
        self.asked: list[str] = []

    def get_results(self, event_id, session_id):
        self.calls += 1
        self.asked.append(session_id)
        answer = self.answers.get(session_id, [])
        if isinstance(answer, Exception):
            raise answer
        return answer


def _row(driver, position):
    return SimpleNamespace(
        id=f"res-{driver.provider_driver_id}-{position}",
        driver=SimpleNamespace(
            id=driver.provider_driver_id,
            first_name=driver.first_name,
            last_name=driver.last_name,
            code=None,
            number=driver.number,
        ),
        team=None,
        position=position,
        grid_position=position,
        status=None,
        points=None,
        fastest_lap_rank=None,
        car_number=driver.number,
        lap_time=f"1:{10 + position}.000",
        display_time=None,
    )


@pytest.fixture()
def race_session(db, season, grid, make_meeting):
    """One race session, scheduled to have finished twenty minutes ago."""
    meeting = make_meeting(1, deadline_at=NOW - timedelta(days=1))
    round_obj = meeting.rounds[0]
    session = Session(
        round_id=round_obj.id,
        provider_session_id="sess-race",
        name="Race",
        type=SESSION_TYPE_RACE,
        stage=STAGE_RACE,
        ordinal=1,
        start_time=NOW - timedelta(hours=1),
        end_time=NOW - timedelta(minutes=20),
        # Deliberately stale. The whole point of the speculative path is that
        # the stored status is out of date during a live weekend.
        status=SESSION_STATUS_SCHEDULED,
    )
    db.session.add(session)
    db.session.commit()
    return session


@pytest.fixture()
def classification(grid):
    return [_row(driver, i + 1) for i, driver in enumerate(grid.drivers)]


# -----------------------------------------------------------------------------
# Finding work
# -----------------------------------------------------------------------------


def test_a_session_due_twenty_minutes_ago_is_work(app, race_session):
    assert [s.id for s in jobs.due_sessions(NOW)] == [race_session.id]


def test_a_session_still_running_is_not(app, race_session):
    assert jobs.due_sessions(NOW - timedelta(hours=2)) == []


def test_a_session_inside_the_grace_period_is_not(app, race_session):
    just_ended = race_session.end_time + timedelta(minutes=1)
    assert jobs.due_sessions(just_ended) == []


def test_a_session_given_up_on_is_stale_rather_than_due(app, race_session):
    much_later = NOW + timedelta(hours=12)
    assert jobs.due_sessions(much_later) == []
    assert [s.id for s in jobs.stale_sessions(much_later)] == [race_session.id]


def test_an_ingested_session_is_never_work_again(app, db, race_session):
    race_session.results_ingested_at = NOW
    db.session.commit()
    assert jobs.due_sessions(NOW) == []
    assert jobs.stale_sessions(NOW + timedelta(hours=12)) == []


def test_practice_is_never_polled(app, db, race_session):
    race_session.stage = STAGE_PRACTICE
    db.session.commit()
    assert jobs.due_sessions(NOW) == []


def test_a_session_with_no_times_is_invisible_rather_than_guessed_at(
    app, db, race_session
):
    race_session.end_time = None
    race_session.start_time = None
    db.session.commit()
    assert jobs.due_sessions(NOW) == []


# -----------------------------------------------------------------------------
# Spending nothing when there is nothing to do
# -----------------------------------------------------------------------------


def test_an_empty_calendar_costs_no_api_calls(app, season):
    provider = FakeProvider()
    outcome = jobs.poll_once(provider, NOW)
    assert provider.calls == 0
    assert not outcome.did_work


def test_an_off_season_tick_costs_no_api_calls(app, race_session):
    """Months after the weekend, the query returns nothing and the tick is
    free. This is the whole of "how does the poller stay quiet"."""
    provider = FakeProvider()
    jobs.poll_once(provider, NOW + timedelta(days=90))
    assert provider.calls == 0


def test_a_quiet_tick_writes_no_run_row(app, season):
    jobs.run_poll(FakeProvider(), NOW)
    assert _db.session.query(WorkerRun).count() == 0


# -----------------------------------------------------------------------------
# Fetching
# -----------------------------------------------------------------------------


def test_one_call_per_due_session(app, race_session, classification):
    provider = FakeProvider({"sess-race": classification})
    outcome = jobs.poll_once(provider, NOW)

    assert provider.calls == 1
    assert provider.asked == ["sess-race"]
    assert outcome.ingested == 1


def test_a_stale_status_does_not_block_the_fetch(app, race_session, classification):
    """The stored status says `scheduled` because the calendar has not been
    resynced since the session ran. Checking it would cost four calls to
    refresh and would still be answering the wrong question."""
    assert race_session.status == SESSION_STATUS_SCHEDULED
    provider = FakeProvider({"sess-race": classification})
    jobs.poll_once(provider, NOW)
    assert race_session.results_ingested_at is not None


def test_results_land_and_the_round_is_scored(app, race_session, classification):
    outcome = jobs.poll_once(FakeProvider({"sess-race": classification}), NOW)
    assert outcome.rounds_scored == 1
    assert _db.session.query(Result).count() == 20


def test_an_empty_answer_means_not_ready_and_stamps_nothing(app, race_session):
    """The failure this guards against is silent and permanent: stamping an
    unrun session as ingested drops it from the game with no error anywhere."""
    outcome = jobs.poll_once(FakeProvider({"sess-race": []}), NOW)

    assert outcome.not_ready == 1
    assert outcome.ingested == 0
    assert not outcome.errors
    assert race_session.results_ingested_at is None


def test_a_404_is_treated_the_same_as_an_empty_answer(app, race_session):
    """Which shape the provider uses for an unpublished session is unknown —
    Season 12 was already finished when this was written — so both mean
    'come back later'."""
    provider = FakeProvider({"sess-race": RuntimeError("404 Not Found")})
    outcome = jobs.poll_once(provider, NOW)

    assert outcome.not_ready == 1
    assert not outcome.errors
    assert race_session.results_ingested_at is None


def test_a_not_ready_session_is_retried_on_the_next_tick(app, race_session, classification):
    provider = FakeProvider({"sess-race": []})
    jobs.poll_once(provider, NOW)

    provider.answers["sess-race"] = classification
    jobs.poll_once(provider, NOW + timedelta(minutes=2))

    assert provider.calls == 2
    assert race_session.results_ingested_at is not None


# -----------------------------------------------------------------------------
# Cadence
# -----------------------------------------------------------------------------


def test_the_patient_phase_stops_asking_every_tick(app, race_session):
    """Inside the eager window every tick asks. Past it, the interval takes
    over — otherwise a session that never publishes would spend a call a minute
    for six hours."""
    jobs._last_attempt.clear()
    provider = FakeProvider({"sess-race": []})

    eager = race_session.end_time + timedelta(minutes=5)
    jobs.poll_once(provider, eager)
    jobs.poll_once(provider, eager + timedelta(minutes=1))
    assert provider.calls == 2

    patient = race_session.end_time + timedelta(minutes=45)
    jobs.poll_once(provider, patient)
    jobs.poll_once(provider, patient + timedelta(minutes=1))
    assert provider.calls == 3

    jobs.poll_once(provider, patient + timedelta(minutes=20))
    assert provider.calls == 4


# -----------------------------------------------------------------------------
# The ceiling
# -----------------------------------------------------------------------------


def test_the_ceiling_stops_the_poller_spending(app, db, race_session, classification):
    db.session.add(WorkerRun(
        job=JOB_POLL,
        started_at=NOW - timedelta(days=1),
        finished_at=NOW - timedelta(days=1),
        ok=True,
        api_calls=app.config["OCB_MONTHLY_CALL_CEILING"],
    ))
    db.session.commit()

    provider = FakeProvider({"sess-race": classification})
    outcome = jobs.poll_once(provider, NOW)

    assert provider.calls == 0
    assert "ceiling" in outcome.skipped_reason
    assert race_session.results_ingested_at is None


def test_the_month_boundary_resets_the_budget(app, db):
    db.session.add(WorkerRun(
        job=JOB_POLL,
        started_at=datetime(2026, 11, 30, 12, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 11, 30, 12, 0, tzinfo=timezone.utc),
        ok=True,
        api_calls=9_000,
    ))
    db.session.commit()
    assert WorkerRun.api_calls_this_month(NOW) == 0


# -----------------------------------------------------------------------------
# Run records
# -----------------------------------------------------------------------------


def test_a_run_records_the_calls_it_spent(app, race_session, classification):
    provider = FakeProvider({"sess-race": classification})
    jobs.run_poll(provider, NOW)

    run = WorkerRun.last_successful(JOB_POLL)
    assert run is not None
    assert run.api_calls == 1
    assert run.detail["ingested"] == 1


def test_a_failed_run_is_recorded_and_reraised(app, season):
    provider = FakeProvider()
    with pytest.raises(ValueError):
        with Run(JOB_POLL, provider=provider):
            raise ValueError("boom")

    run = _db.session.query(WorkerRun).one()
    assert run.ok is False
    assert "boom" in run.summary
    assert run.finished_at is not None


def test_an_unfinished_run_survives_pruning(app, db):
    """A row with no finish is the only evidence a crash leaves, so the
    retention sweep must not tidy it away."""
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.session.add(WorkerRun(job=JOB_POLL, started_at=old))
    db.session.add(WorkerRun(job=JOB_POLL, started_at=old, finished_at=old, ok=True))
    db.session.commit()

    assert WorkerRun.prune(30, now=NOW) == 1
    db.session.commit()
    assert _db.session.query(WorkerRun).count() == 1


# -----------------------------------------------------------------------------
# The sync
# -----------------------------------------------------------------------------


def test_the_target_season_is_the_ending_year():
    """A season runs December to July and is keyed by the year it ends, so from
    August the worker is already looking for next season."""
    assert jobs.target_season_year(datetime(2026, 8, 1, tzinfo=timezone.utc)) == 2027
    assert jobs.target_season_year(datetime(2026, 12, 19, tzinfo=timezone.utc)) == 2027
    assert jobs.target_season_year(datetime(2027, 3, 1, tzinfo=timezone.utc)) == 2027
    assert jobs.target_season_year(datetime(2027, 8, 1, tzinfo=timezone.utc)) == 2028


def test_a_sync_is_due_when_none_has_ever_run(app, season):
    assert jobs.sync_is_due(NOW)


def test_a_recent_sync_is_not_repeated(app, db, season):
    db.session.add(WorkerRun(
        job=JOB_SEASON_SYNC,
        started_at=NOW - timedelta(hours=1),
        finished_at=NOW - timedelta(hours=1),
        ok=True,
    ))
    db.session.commit()
    assert not jobs.sync_is_due(NOW)


def test_an_imminent_session_shortens_the_sync_interval(
    app, db, season, race_session
):
    """A schedule change matters most just before a weekend: a deadline that
    moved is a lineup nobody could set."""
    db.session.add(WorkerRun(
        job=JOB_SEASON_SYNC,
        started_at=NOW - timedelta(hours=8),
        finished_at=NOW - timedelta(hours=8),
        ok=True,
    ))
    race_session.start_time = NOW + timedelta(hours=10)
    race_session.end_time = NOW + timedelta(hours=11)
    db.session.commit()

    assert jobs.sync_is_due(NOW)
