"""Season 12 scoring simulation.

Sits outside `app/` deliberately (SPEC.md §12): there is no import path by which
the web application can be pulled into this, and no route by which this can
accidentally depend on Flask.

Reads the backfilled data with plain SQL and feeds plain dicts to
`app.scoring`. The only thing it imports from the application is the scoring
rules and engine, which are pure by construction.
"""
