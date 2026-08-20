# Phase 3, step 9 — layout corrections

No migration, no dependency. Four files.

```
app/static/css/primitives.css           star/score, sheet, underlines, band
app/styleguide/scoring_bridge.py        Perfect Five
app/templates/styleguide/_lineup.html   verdict macro, stacked figure, band
app/templates/styleguide/lineup.html    verdict above the lineup
```

```bash
cd ~/projects/fe-fantasy
tar xzf ~/fe-phase3-step9.tar.gz
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

## The star collision, and why it happened

The star and the score were both positioned absolutely against the slot, which
is why they met on the team slot: two things placed by coordinates rather than
by layout will eventually collide, and it is only a question of which content
length finds it.

So neither is absolute any more. They share one column, stacked, star above
score, aligned right. They now cannot overlap in any slot, at any score length,
in any state — and the fix removes code rather than adding a special case.

## The sticky header, same root cause

Picker rows were painting over the sheet's heading rather than scrolling under
it. `.option` is `position: relative`, and positioned siblings without a
`z-index` paint in DOM order — so every row, being later in the document, drew
on top of the header. One `z-index` on the header fixes it.

## Modal position

Centred, sized to content, with a ceiling. Short content floats with the
backdrop visible on all four edges; long content grows to the ceiling and
scrolls, at which point the sheet reaching the bottom of the screen is itself
the signal that there is more below — which is the behaviour you liked on the
driver picker, now arrived at by rule rather than by accident.

## Underlines

`.slot`, `.option`, and the action buttons no longer carry them. Your diagnosis
was right: the scored screen looks cleaner because nothing there is a link.
These are links only because they navigate — they are not prose. Genuine inline
links in prose keep their underline.

## Team colour in a breakdown

The modal header now carries the pick's team band, with the constructor name
under the driver's. A breakdown opened over a dimmed page says whose it is
without relying on you remembering which slot you tapped. The team pick's
header uses the split band, same as its slot.

## Perfect Five

Renamed throughout. Still one constant in `scoring_bridge.py`.

## The verdict

Now sits between the masthead and the lineup, as its own row. It reads better
there than I expected — it is the answer the screen exists to give, and an
answer belongs at the top rather than as a footer to the evidence.

## Worth checking

- Scored → a meeting where your team pick made the Perfect Five. Star above the
  score, no overlap.
- Transfers → open the picker and scroll. Rows should pass cleanly under the
  heading.
- Any short modal — the reset-free commit confirmation is the shortest — should
  now float centred with backdrop on all four sides.

Commit message:

```
Stack star above score, fix sheet header stacking and modal centring, drop
control underlines, rename dream team to Perfect Five
```
