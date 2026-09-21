"""The worker. `python -m worker.tick`, run by Railway cron every five minutes.

One run does everything that is due, once, and exits. There is no scheduler,
no long-lived process and no in-memory state: every decision about what is due
is derived from the schedule and from `WorkerRun`, so a run knows exactly as
much as the one before it did.

Railway skips a scheduled run while the previous one is still active, which is
what makes overlapping polls impossible. The old one-replica rule was a setting
nobody could enforce from inside the process; this one the platform enforces.
The cost is that a run which hung would silently stop all polling, which is
why every run has a hard ceiling well inside the cron interval.

The cron interval and `POLL_INTERVAL_SECONDS` must agree. The patient phase of
the poll counts ticks by that value (see `worker.jobs`), and the process has no
way to read its own cron expression.

Exit codes are honest: 0 when everything ran, 1 when a job raised or the run
hit its ceiling. The service's restart policy must be Never, or a failed run is
retried immediately, which during a race weekend spends quota on the same
failure again.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
from datetime import datetime, timedelta, timezone

from app import create_app
from app.extensions import db
from app.models.worker import JOB_POLL, RUN_CEILING_SECONDS, WorkerRun
from app.providers.ocblacktop import OCBlacktopProvider
from worker import jobs, runs
from worker.runs import Run

log = logging.getLogger("worker")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _on_ceiling(signum, _frame) -> None:
    # os._exit rather than raising: an exception raised from a signal handler
    # lands wherever the main thread happens to be, and a job's own `except`
    # could swallow it and carry on. The unfinished WorkerRun row this leaves
    # behind is the crash evidence `runs.py` is designed to keep.
    log.error("Run exceeded %ss; exiting", RUN_CEILING_SECONDS)
    logging.shutdown()
    os._exit(1)


def _heartbeat_due(app, now: datetime) -> bool:
    """Whether an hour has passed without a successful poll row.

    Derived from the table rather than a process global, so the admin page's
    liveness check reads exactly as it did under the long-running worker.
    """
    interval = timedelta(minutes=app.config["WORKER_HEARTBEAT_MINUTES"])
    last = WorkerRun.last_successful(JOB_POLL)
    return last is None or now - last.started_at >= interval


def run_once(app, provider, now: datetime | None = None) -> bool:
    """Everything that is due, once. Returns False if any part failed.

    Each job is isolated: a failing poll must not stop the calendar sync, and
    the reverse. The poll goes first because it is the time-sensitive one.
    """
    now = now or _utcnow()
    ok = True

    try:
        outcome = jobs.run_poll(provider, now)
        if outcome.did_work:
            log.info("Poll: %s", outcome.summary())
        elif _heartbeat_due(app, now):
            with Run(JOB_POLL, provider=provider) as run:
                run.summary = "idle"
                run.detail = {"idle": True}
    except Exception:
        log.exception("Poll failed")
        db.session.rollback()
        ok = False

    try:
        summary = jobs.run_sync(provider, now)
        if summary:
            log.info("Sync: %s", summary)
    except Exception:
        log.exception("Sync failed")
        db.session.rollback()
        ok = False

    # One indexed DELETE. Cheaper to run every tick than to decide whether
    # today's has happened yet.
    try:
        runs.prune(now)
    except Exception:
        log.exception("Housekeeping failed")
        db.session.rollback()
        ok = False

    return ok


def main() -> int:
    signal.signal(signal.SIGALRM, _on_ceiling)
    signal.alarm(RUN_CEILING_SECONDS)

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

    # One provider for the whole run, so its throttle keeps this run's
    # requests a second apart. Runs are five minutes apart, so nothing needs
    # to carry between them.
    provider = OCBlacktopProvider.from_config(app.config)

    with app.app_context():
        try:
            ok = run_once(app, provider)
        finally:
            # Railway expects a cron process to leave nothing open.
            db.session.remove()
            db.engine.dispose()

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
