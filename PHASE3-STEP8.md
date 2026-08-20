# Phase 3, step 8 — modals, Maximum Attack, and the verdict

No migration, no dependency. `palette.py` stays out; `tokens.css` is unchanged
and also absent.

```
app/styleguide/__init__.py              best-lineup view, committed in context
app/styleguide/scoring_bridge.py        fmt, places wording, per-round team fix,
                                        meeting_best_lineup
app/static/css/primitives.css           verdict, aside, restore, sheet, team slot
app/templates/styleguide/_lineup.html   modal breakdowns, verdict
app/templates/styleguide/lineup.html    modal script, Maximum Attack, restore
app/templates/styleguide/meeting.html   highlighting removed
```

```bash
cd ~/projects/fe-fantasy
tar xzf ~/fe-phase3-step8.tar.gz
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

## Dialogs are actually modal now

This was a bug, not a design decision. A `<dialog>` rendered with the `open`
attribute displays inline — no backdrop, no page fade, no focus trap, no
escape-to-close. `showModal()` is what makes it modal, and that is why the
picker was appearing in the flow of the page.

Both the picker and the breakdown now open over the page with the background
dimmed. Tapping the backdrop closes, as does escape. **The breakdown's internal
layout is untouched** — only the vessel changed.

## Fixes

**Team slot rules back to a hairline.** Heavy is for regions — masthead from
lineup, lineup from verdict. On a slot it read as a region boundary rather than
as a fifth pick. The recessed ground stays.

**Places gained now reads "8 places".** The stage's context line already says
"Started P13 · finished P5", so repeating it wasted the row; the figure the
rule counted is what produced the points. Rewritten in the adapter, since it is
wording and the engine has no business knowing how a rule is phrased.

**The team's per-round detail bug is fixed.** You read it exactly right —
`aggregate_meeting` took the "half of…" text once from the first round and
reused it for both, so round 8 showed round 7's cars. It now lives on
`RoundDetail`, where it belongs.

**Number formatting.** `26.0` becomes `26`; `5.5` stays `5.5`. Halves are real
and SPEC §3 forbids rounding them, but a Decimal's trailing zero is an artefact
of arithmetic rather than a fact about the score.

**Reset is instant.** No confirmation.

**Restore.** Open the picker on a slot carrying an **In** tag and a "Put back"
section sits above the roster listing what this draft swapped out. Every
outgoing pick is offered rather than a guessed pairing — once two slots have
moved, which original replaced which is genuinely ambiguous. Usually it is one
row.

**Results is results.** No highlighting of your own picks, for the reason you
gave: correct highlighting needs the lineup as it stood at that round, and
round 4's picks shown while reading round 15 confuse more than they help.

## The verdict

The weekend total is now an inverted slab: ink ground, paper text, the figure
in Anybody at 3.4rem — far larger than any slot score. It is the only dark
element in the app, which is what makes it read as the conclusion rather than
as another row. The page ground stays paper, so §1 is intact.

It is built as a stack with a `.verdict__row` class already defined and unused,
so "average this week" or "highest score" drop in beneath the headline figure
without a redesign.

## Maximum Attack

The best lineup for the weekend has its own route: the same screen with a
different lineup in it, which is the shape the reader already knows. A quiet
link sits under the lineup, and a starred pick's breakdown carries a second
link to it.

This is a **meeting-level** computation, not per-round: a double-header scores
one lineup twice, so the question is which five picks maximise the sum. Stars
in the lineup therefore mean "in the weekend's best lineup", consistent with the
combined total they sit beside.

One thing I could not do as described: the star cannot itself be the tap
target, because nesting a link inside the slot's button is invalid HTML and
breaks keyboard navigation. Two routes to the same place instead — the aside
link, and the link inside a starred pick's breakdown.

The name is `DREAM_TEAM_NAME` in `scoring_bridge.py`. One edit if you want
"Perfect Five" or anything else.

## Worth checking

- Scored → tap a driver. The breakdown should open over the page, dimmed
  behind, closing on backdrop or escape.
- Scored → meeting 6, tap the team pick. The two rounds should now name
  different cars with different scores.
- Transfers → swap a driver, reopen that slot, use "Put back".
- The verdict: too loud, or right?

Commit message:

```
Make dialogs modal; add the Maximum Attack view and the verdict block; fix
per-round team detail and score formatting
```
