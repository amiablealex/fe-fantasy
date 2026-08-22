"""The worker process. `python -m worker.scheduler`.

One replica, always. APScheduler holds its schedule in process, so a second
instance double-fires every job — which against a rate-limited free tier means
429s rather than duplicate work. This is set on the Railway service, not here,
and there is no way to enforce it from inside the process.

The scheduler does no work of its own. It owns the clock, the app context and
one long-lived provider — long-lived because the provider carries the throttle
state that keeps requests a second apart, and a fresh instance per tick would
forget it and burst.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app import create_app
from app.providers.ocblacktop import OCBlacktopProvider
from worker import jobs, runs
from app.models.worker import JOB_POLL
from worker.runs import Run

log = logging.getLogger("worker")

_last_heartbeat: datetime | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _heartbeat(app, provider) -> None:
    """Prove the worker is alive on a quiet day.

    Without this, a worker that died in October and a worker idling correctly
    through the summer break look identical on the admin page — both show a
    last run from whenever something last happened.
    """
    global _last_heartbeat
    now = _utcnow()
    interval = timedelta(minutes=app.config["WORKER_HEARTBEAT_MINUTES"])
    if _last_heartbeat is not None and now - _last_heartbeat < interval:
        return
    _last_heartbeat = now
    with Run(JOB_POLL, provider=provider) as run:
        run.summary = "idle"
        run.detail = {"idle": True}


def tick(app, provider) -> None:
    with app.app_context():
        try:
            outcome = jobs.run_poll(provider)
            if outcome.did_work:
                log.info("Poll: %s", outcome.summary())
            else:
                _heartbeat(app, provider)
        except Exception:
            log.exception("Poll tick failed")


def sync_tick(app, provider) -> None:
    with app.app_context():
        try:
            summary = jobs.run_sync(provider)
            if summary:
                log.info("Sync: %s", summary)
        except Exception:
            log.exception("Sync tick failed")


def housekeeping(app) -> None:
    with app.app_context():
        try:
            runs.prune()
        except Exception:
            log.exception("Housekeeping failed")


def build_scheduler(app, provider) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    poll_seconds = app.config["POLL_INTERVAL_SECONDS"]

    # An interval trigger otherwise schedules its first fire at now + interval,
    # so a fresh deploy would sit for fifteen minutes before looking at the
    # calendar. Both jobs are safe to run immediately: the poll opens with a
    # free query, and the sync has its own due check.
    start_now = _utcnow()

    # `coalesce` and `max_instances=1` together mean a slow tick delays the
    # next one rather than running alongside it. Two concurrent polls would
    # fetch the same session twice and spend twice the quota to do it.
    scheduler.add_job(
        tick, "interval", seconds=poll_seconds,
        args=[app, provider], id="poll",
        max_instances=1, coalesce=True, misfire_grace_time=poll_seconds,
        next_run_time=start_now,
    )
    scheduler.add_job(
        sync_tick, "interval", minutes=15,
        args=[app, provider], id="sync",
        max_instances=1, coalesce=True,
        next_run_time=start_now,
    )
    scheduler.add_job(
        housekeeping, "interval", hours=24,
        args=[app], id="housekeeping",
        max_instances=1, coalesce=True,
    )
    return scheduler


def main() -> int:
    app = create_app()

    if not app.config.get("OCB_API_KEY"):
        log.error("OCB_API_KEY is not set. The worker has nothing to poll with.")
        return 1

    if os.environ.get("FANTASY_NOW"):
        # The clock override moves the app's idea of "now" for the lineup
        # editor. The worker deliberately ignores it and runs on real UTC: a
        # stale value here would send it chasing a weekend from last December.
        log.warning(
            "FANTASY_NOW is set in the worker environment and is being ignored."
        )

    # APScheduler logs "Looking for jobs to run" at DEBUG on every wakeup,
    # which under FLASK_ENV=development is a line a minute forever.
    logging.getLogger("apscheduler").setLevel(logging.INFO)

    provider = OCBlacktopProvider.from_config(app.config)
    scheduler = build_scheduler(app, provider)

    log.info(
        "Worker starting: poll every %ss, sync check every 15m",
        app.config["POLL_INTERVAL_SECONDS"],
    )
    scheduler.start()
    return _wait(scheduler)


def _wait(scheduler) -> int:
    """Block until SIGTERM or SIGINT, then shut down cleanly.

    Railway sends SIGTERM on redeploy. Letting the current tick finish means a
    session that was mid-ingest commits rather than rolling back and being
    refetched — one saved call, and one less confusing gap in the run history.
    """
    import threading

    stopping = threading.Event()

    def _stop(signum, _frame):
        log.info("Signal %s received; shutting down", signum)
        stopping.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    stopping.wait()
    scheduler.shutdown(wait=True)
    log.info("Worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
