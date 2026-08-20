# Phase 3, step 11 — context, disclosure, quieter tabs

```bash
cd ~/projects/fe-fantasy
tar xzf ~/fe-phase3-step11.tar.gz
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

```
app/styleguide/__init__.py              no view param; results always loaded
app/static/css/primitives.css           context line, disclosure, tab restyle
app/templates/styleguide/_nav.html       context line; view switch removed
app/templates/styleguide/_results.html   switch links target the disclosure
app/templates/styleguide/lineup.html     results as a disclosure
```

## Round context is back

Under the meeting name:

    ‹        11 London        ›
       DOUBLE-HEADER · ROUNDS 16 AND 17

A single-header reads "Round 9". The arrow nav removed the numbered strip and
took this with it — the name alone never said which rounds London contains.

## Results is a disclosure

Collapsed by default, sitting under the Perfect Five link. Your earlier
objection to stacking was right, and collapsing answers it: a reader who came
for their own score pays nothing, and the section costs one line until asked
for.

It is a native `<details>`, so there is no JavaScript, and it is keyboard and
screen-reader correct without any ARIA.

The round and stage switches keep it open by carrying `results=open` in the
URL and anchoring to `#results`, so switching stage returns you to the same
place rather than collapsing the section. No script needed to remember state.

The tab row you disliked is gone entirely; there is no `?view=` parameter any
more.

## Quieter tabs

The round and stage switches are underline tabs now, matching the language the
rest of the app already uses. A filled black tab beside an unfilled one puts a
large solid rectangle in the middle of a results page, which reads as more
important than the results underneath it.

They also read "Round 16" rather than "16".

## Breakdown alignment

The round heading's score is back on the right edge. When the round number was
folded into the label, the header's grid still declared three columns for two
children — so the total sat against the text instead of taking the right
column.

## Worth checking

- A single-header meeting: the round switch should not appear at all, leaving
  one thin row of chrome inside Results.
- Open Results, switch to Qualifying, then to Round 17 — the section should
  stay open and stay in view.
- The context line at 360px on the longest name (Monte Carlo).

Commit message:

```
Restore round context to the meeting nav; move results into a disclosure and
restyle the switches as underline tabs
```
