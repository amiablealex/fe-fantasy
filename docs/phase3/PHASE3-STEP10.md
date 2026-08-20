# Phase 3, step 10 — meeting navigation and the Results view

Start this on the new branch:

```bash
git checkout -b phase3-navigation      # if you have not already
tar xzf ~/fe-phase3-step10.tar.gz
rm app/templates/styleguide/meeting.html
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

```
new       app/templates/styleguide/_nav.html      meeting nav, menu, view switch
new       app/templates/styleguide/_results.html  results, qualifying, schedule
replaced  app/styleguide/__init__.py              nav + results routing
replaced  app/styleguide/scoring_bridge.py        meeting refs, results, schedule
replaced  app/static/css/primitives.css           nav, switches, schedule
replaced  app/templates/styleguide/_lineup.html   "Round 16" labels
replaced  app/templates/styleguide/lineup.html    restructured around the nav
replaced  app/templates/styleguide/_shell.html    one Meeting entry
deleted   app/templates/styleguide/meeting.html   folded in as a view
```

The `/styleguide/meeting` route is gone; Results is now a view of the meeting
page. Delete the old template as shown above.

## The shape

```
‹   11 London   ›
[ Your weekend | Results ]
```

One masthead, one nav, two peer views. Opening `/styleguide/lineup` with no
meeting lands on the **latest meeting with results**, which is what a player
wants on arrival.

**Arrows move by one**, which is almost every move. At either end the arrow
goes flat rather than disappearing — a control that vanishes shifts the layout
and teaches nothing.

**Tapping the name opens the weekend list**, in the sheet vessel we already
have, with the current one marked and unraced ones labelled. That covers the
jump case and removes any need for a separate "back to current" button.

## Inside Results

Two thin levels, not one flat four-way:

```
[ 16 E-Prix Unleashed | 17 E-Prix ]     ← double-headers only
[ Qualifying | Race ]
```

A single-header never renders the first row, so the common case stays quiet.

**Qualifying is a placeholder.** Every session in bracket order with its
classification — honest and readable, and the entire contents of that macro get
replaced by the bracket next step. The container is what matters here.

## Before a weekend is raced

Results shows **the schedule** — every session, its type, and its time, taken
from data already ingested. Practice and shakedown sessions are included even
though they are never ingested for results: the reader wants the weekend, not
the scoring surface.

Try meeting 9 or later in S12 if your backfill is partial, or any S13 meeting
once that syncs.

## Also

Breakdown round headings now read "Round 16 · E-Prix" rather than "16 E-Prix".

## Worth checking

- Arrows at meeting 1 and at the last one — both should be flat, not missing.
- The weekend list: does it feel better than the numbered strip?
- Results → a double-header → switch rounds and stages. Is three rows of chrome
  too much at 360px? This is the part I am least sure of, and the bracket has
  to live under it.

Commit message:

```
Replace the meeting strip with arrow navigation; fold results into the meeting
page as a peer view with a schedule fallback
```
