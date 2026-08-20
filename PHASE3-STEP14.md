# Phase 3, step 14 — table structure and in-place profiles

```bash
cd ~/projects/fe-fantasy
tar xzf ~/fe-phase3-step14.tar.gz
source .venv/bin/activate
python -m pyflakes app/styleguide/*.py
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

```
new       app/templates/styleguide/_profile_sheet.html
replaced  app/styleguide/__init__.py              /styleguide/lineup/profile
replaced  app/static/css/primitives.css           table dividers, padding, spacing
replaced  app/templates/styleguide/_lineup.html   breakdown hx
replaced  app/templates/styleguide/_profile.html  grouped header
replaced  app/templates/styleguide/_results.html  names swap in place
replaced  app/templates/styleguide/_results_body.html
replaced  app/templates/styleguide/lineup.html    delegated handlers, host
```

## The two vertical lines

Both were intentional — one separates TP from the rules it sums, the other
separates qualifying from race. But you read them as a rendering fault, and you
were right to: a divider with nothing naming what it divides is noise.

So the table gains a grouped header row:

    R   TP │ QUALIFYING      │ RACE
             GRP  DW   POL     WIN  POD  PTS  FL  ±PL

Now the lines are structure rather than debris. Cell padding is symmetric too,
so a divider sits in space instead of against the digits either side of it.

## The team table's outer line

`TEAM` is the last column there, so a divider on its trailing edge drew a line
down the outer edge of the table. It takes the divider on its leading edge
instead, where it still separates the sum from the halves it came from.

## Spacing under the stage switch

The switch is chrome and what follows is content; butted together they read as
one crowded block. There is a proper gap now.

## Profiles open without losing your place

This was worth fixing properly rather than living with. Opening a profile was a
full navigation, so the meeting page reloaded and scrolled to the top — tapping
a driver halfway down a classification sent you back to the beginning.

Profiles now swap in via HTMX, exactly as the results switches already do. The
page does not move; closing returns you to the row you tapped.

Two things that make it hold together:

- The links keep their plain `href`, so without JavaScript they navigate as
  before. The server still renders the profile for that path.
- The click handlers are **delegated from the document** rather than bound per
  element, so markup HTMX swaps in behaves like markup that was there at load.
  Binding per element is the usual way this breaks the second time something is
  swapped.

## Worth checking

- A driver profile: the header should read QUALIFYING and RACE over their
  columns, and the two dividers should line up with those groups.
- Scroll halfway down a classification, tap a driver, close the profile — the
  page should not have moved.
- Open a profile from the picker and close it: the picker should still be open
  on the same slot.
- A team profile: no line down the right-hand edge.

Commit message:

```
Group profile table columns under qualifying and race; swap profiles in place
without losing scroll position
```
