"""Running versus killed: the one judgement the health page makes per row."""
from datetime import datetime, timedelta, timezone

from app.models.worker import RUN_CEILING_SECONDS, WorkerRun


def _run(age_seconds: int, finished: bool = False) -> WorkerRun:
    now = datetime.now(timezone.utc)
    return WorkerRun(
        job="poll",
        started_at=now - timedelta(seconds=age_seconds),
        finished_at=now if finished else None,
    )


def test_open_run_inside_the_ceiling_is_running():
    run = _run(RUN_CEILING_SECONDS - 30)
    assert run.is_running and not run.is_killed


def test_open_run_past_the_ceiling_is_killed():
    run = _run(RUN_CEILING_SECONDS + 30)
    assert run.is_killed and not run.is_running


def test_finished_run_is_neither():
    run = _run(RUN_CEILING_SECONDS + 30, finished=True)
    assert not run.is_running and not run.is_killed
