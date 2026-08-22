"""The background worker.

Two jobs, one process, one replica:

    poll   every minute. Fetches results for sessions the stored schedule says
           have finished, then scores whatever became scoreable.
    sync   a few times a day. Refreshes the calendar and, off-season, watches
           for the next season to be published.

Deliberately outside `app/`, like `sim/`. Nothing in the web application
imports this, and the direction is enforced by there being no route by which it
could.
"""
