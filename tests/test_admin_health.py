"""The admin health page.

The judgements — is the worker silent, is the budget over, which sessions were
given up on — live in `app/admin/health.py` rather than in the template, so
they can be tested here rather than by reading rendered HTML.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.admin import health as health_queries
from app.models.calendar import (
    SESSION_STATUS_SCHEDULED,
    SESSION_TYPE_RACE,
    STAGE_RACE,
    Session,
)
from app.models.worker import JOB_POLL, JOB_SEASON_SYNC, WorkerRun

NOW = datetime(2026, 12, 19, 18, 0, tzinfo=timezone.utc)


def _run(db, job, *, minutes_ago=5, calls=0, ok=True, finished=True, summary=None):
    started = NOW - timedelta(minutes=minutes_ago)
    row = WorkerRun(
        job=job,
        started_at=started,
        finished_at=started if finished else None,
        ok=ok if finished else None,
        api_calls=calls,
        summary=summary,
    )
    db.session.add(row)
    db.session.commit()
    return row


def _race_session(db, meeting, *, ends, ingested=None):
    session = Session(
        round_id=meeting.rounds[0].id,
        provider_session_id=f"sess-{meeting.id}",
        name="Race",
        type=SESSION_TYPE_RACE,
        stage=STAGE_RACE,
        ordinal=1,
        start_time=ends - timedelta(hours=1),
        end_time=ends,
        status=SESSION_STATUS_SCHEDULED,
        results_ingested_at=ingested,
    )
    db.session.add(session)
    db.session.commit()
    return session


# -----------------------------------------------------------------------------
# Relative time
# -----------------------------------------------------------------------------


def test_ago_uses_the_largest_useful_unit():
    assert health_queries.ago(NOW - timedelta(seconds=30), NOW) == "30s ago"
    assert health_queries.ago(NOW - timedelta(minutes=20), NOW) == "20m ago"
    assert health_queries.ago(NOW - timedelta(hours=5), NOW) == "5h ago"
    assert health_queries.ago(NOW - timedelta(days=3), NOW) == "3d ago"
    assert health_queries.ago(None, NOW) is None


def test_ago_does_not_report_a_negative_duration():
    assert health_queries.ago(NOW + timedelta(minutes=5), NOW) == "just now"


# -----------------------------------------------------------------------------
# The worker
# -----------------------------------------------------------------------------


def test_a_worker_that_has_never_run_reads_as_silent(app):
    worker = health_queries.snapshot(NOW).worker
    assert not worker.has_ever_run
    assert worker.is_silent


def test_a_recent_heartbeat_is_not_silence(app, db):
    _run(db, JOB_POLL, minutes_ago=20, summary="idle")
    assert not health_queries.snapshot(NOW).worker.is_silent


def test_silence_is_twice_the_heartbeat_interval(app, db):
    """The heartbeat exists so a quiet worker and a dead one look different.
    Anything past two intervals means it stopped reporting."""
    limit = app.config["WORKER_HEARTBEAT_MINUTES"]
    _run(db, JOB_POLL, minutes_ago=limit * 2 + 1, summary="idle")
    assert health_queries.snapshot(NOW).worker.is_silent


def test_only_successful_runs_count_as_the_last_poll(app, db):
    _run(db, JOB_POLL, minutes_ago=60, summary="1 ingested")
    _run(db, JOB_POLL, minutes_ago=5, ok=False, summary="boom")

    worker = health_queries.snapshot(NOW).worker
    assert worker.since(worker.last_poll) == "60m ago"
    # But the failure still proves the worker is alive.
    assert not worker.is_silent


def test_an_open_run_is_counted(app, db):
    _run(db, JOB_POLL, minutes_ago=1, finished=False)
    assert health_queries.snapshot(NOW).worker.unfinished == 1


# -----------------------------------------------------------------------------
# The budget
# -----------------------------------------------------------------------------


def test_the_budget_sums_the_calendar_month(app, db):
    _run(db, JOB_SEASON_SYNC, minutes_ago=60, calls=6)
    _run(db, JOB_POLL, minutes_ago=30, calls=4)

    budget = health_queries.snapshot(NOW).budget
    assert budget.used == 10
    assert budget.remaining == budget.ceiling - 10
    assert not budget.is_over


def test_the_budget_goes_over_at_the_ceiling(app, db):
    _run(db, JOB_POLL, minutes_ago=5, calls=app.config["OCB_MONTHLY_CALL_CEILING"])
    budget = health_queries.snapshot(NOW).budget
    assert budget.is_over
    assert budget.remaining == 0


# -----------------------------------------------------------------------------
# Results and scoring
# -----------------------------------------------------------------------------


def test_a_session_past_the_give_up_window_is_reported_as_stale(
    app, db, season, make_meeting
):
    meeting = make_meeting(1)
    _race_session(db, meeting, ends=NOW - timedelta(hours=12))

    health = health_queries.snapshot(NOW)
    assert len(health.stale) == 1
    assert health.awaiting == 1
    assert health.needs_attention


def test_an_ingested_session_is_neither_awaited_nor_stale(
    app, db, season, make_meeting
):
    meeting = make_meeting(1)
    _race_session(db, meeting, ends=NOW - timedelta(hours=12), ingested=NOW)

    health = health_queries.snapshot(NOW)
    assert health.stale == []
    assert health.awaiting == 0


def test_scoring_coverage_counts_rounds_by_state(app, db, season, make_meeting):
    meeting = make_meeting(1, rounds=2)
    meeting.rounds[0].scored_at = NOW
    meeting.rounds[0].scoring_provisional = False
    meeting.rounds[1].scored_at = NOW
    meeting.rounds[1].scoring_provisional = True
    db.session.commit()

    row = health_queries.snapshot(NOW).seasons[0]
    assert row.rounds == 2
    assert row.scored == 2
    assert row.provisional == 1
    assert row.unscored == 0
    assert not row.is_complete


def test_a_fully_scored_season_is_complete(app, db, season, make_meeting):
    meeting = make_meeting(1)
    meeting.rounds[0].scored_at = NOW
    db.session.commit()
    assert health_queries.snapshot(NOW).seasons[0].is_complete


def test_an_unscored_round_is_not_provisional(app, db, season, make_meeting):
    """Provisional means "scored from part of the sessions", which a round that
    has never been scored is not."""
    make_meeting(1)
    row = health_queries.snapshot(NOW).seasons[0]
    assert row.scored == 0
    assert row.provisional == 0
    assert row.unscored == 1


# -----------------------------------------------------------------------------
# The page
# -----------------------------------------------------------------------------


def test_the_health_page_needs_admin(client, signed_in):
    signed_in()
    assert client.get("/admin/health").status_code == 403


def test_an_admin_sees_the_health_page(client, signed_in):
    signed_in(is_admin=True)
    response = client.get("/admin/health")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Provider calls this month" in body
    assert "Sync conflicts" in body


def test_the_page_renders_with_nothing_recorded(client, signed_in):
    """The state production is in right now: no seasons, no runs, no results.
    It has to render rather than divide by zero somewhere."""
    signed_in(is_admin=True)
    body = client.get("/admin/health").get_data(as_text=True)
    assert "never" in body
    assert "None outstanding." in body


def test_the_admin_index_links_to_health(client, signed_in):
    signed_in(is_admin=True)
    body = client.get("/admin/").get_data(as_text=True)
    assert "/admin/health" in body
