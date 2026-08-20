# Phase 3, step 6 — hierarchy, and the visual pass

No migration, no dependency. `palette.py` stays out; `tokens.css` is in because
it gains three tokens.

```
app/static/css/tokens.css               --rule-heavy, --band-*
app/static/css/primitives.css           slot, band, breakdown, option meta
app/styleguide/scoring_bridge.py        notes, car numbers
app/templates/styleguide/_lineup.html   band, ghost numeral, round blocks
app/templates/styleguide/lineup.html    picker note position
```

```bash
cd ~/projects/fe-fantasy
tar xzf ~/fe-phase3-step6.tar.gz
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

## The four fixes

**Round separation.** A double-header breakdown is now two blocks, each with
its own heading — round number in the display face, format, subtotal — on a
recessed strip, with the body indented behind a rule. The two races no longer
run together.

**The context line reads as context.** It has moved inside the stage heading,
above the rule, set smaller and condensed. Before, it sat in the rows' column
looking like a rule that had failed to score, which is exactly backwards: it is
the reason the rows below say what they say.

    QUALIFYING                          8
    Won the Final — pole position
    ─────────────────────────────────────
    Reached the Duels  Group 2 P4       2
    Duel win  Quarter-Final 4           1

**Picker notes moved right.** Two lines in the right column — a small "In your
lineup" label above the names — so the left stays driver over team, as it did
in the greyed version.

**Notes name every driver.** Holding both Andretti cars and opening the team
list now reads "Dennis and Mortara", not one of them. It was taking the first
holder rather than all of them.

## The visual pass

Diagnosis first: the newspaper feel was not a shortage of decoration. It was a
missing middle layer — no figure/ground anywhere, and near-uniform rule weight,
so everything sat on one flat plane. Four changes, none of which needs a
gradient, a shadow, a rounded card or an icon.

**Slots are objects now.** A driver slot is a filled block on a recessed
ground; the team slot inverts it, paper between two heavy rules. A different
class of pick is a different kind of *surface*, with nothing labelling it.

**The team band.** The primary hue runs the full inner edge of the slot with
the secondary as a thinner accent inside it — your call, and the right one. At
slot scale two equal stripes read as a pattern; a band with an accent reads as
a livery.

**The car number, ghosted.** Set large and barely inked behind the name,
clipped by the slot. Formula E cars carry their numbers, so this is the sport's
own vocabulary used as a typographic ground — decoration's job done by type,
which is the §1 design value stated outright. It is the one piece of real flair
in the pass, and the one most worth telling me to remove if it is wrong.

**Scale and rule hierarchy.** The score jumps to `--step-7`, a long way above
everything around it — scale contrast is the cheapest hierarchy available and
the page was not using it. Rules now come in three deliberate weights: hair
between rows, mark between sections, heavy between regions.

## What to judge

- Do the slots read as objects, or is the recessed fill too subtle?
- The ghost numeral at 360px: depth, or clutter? Check `Drugovich` and
  `Di Grassi`, the longest names.
- Is the team slot obviously a different class of thing now?
- Double-header breakdown, meeting 6: are the two rounds clearly separate?

## Next

The bracket, which closes Phase 3 — now designed inside a settled language
rather than ahead of one.

Commit message:

```
Add figure/ground, team band and rule hierarchy to the lineup; separate rounds
and fix picker notes
```
