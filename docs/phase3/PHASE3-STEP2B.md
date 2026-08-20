# Phase 3, step 2b — palette revision

Same branch, same debug-only blueprint, no migration, no new dependency.
Four files are replaced in place. Nothing is added or deleted.

```
app/palette.py                    rewritten — two stripes, achromatic seeds
app/static/css/tokens.css         tint, achromatic and gutter tokens
app/static/css/primitives.css     team mark and yours-marking rewritten
app/static/css/styleguide.css     swatches show real stripes
app/templates/styleguide/index.html
```

## 1. Extract and run

```bash
cd ~/projects/fe-fantasy
tar xzf ~/fe-phase3-step2b.tar.gz
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

Hard-refresh on the phone — the CSS filenames are unchanged, so a cached
stylesheet will show you the old design.

## 2. What changed

**Anybody is settled at width 100, weight 700**, written into `tokens.css` as
`--display-width` and `--display-weight`. Those buttons are gone from the bar.

**Every team now has two stripes.** The primary, then either a declared
secondary or a lighter tint of the same hue derived in the browser. The tint
costs nothing to maintain, so the four red teams can be separated by giving
just those a real second colour rather than filling in twenty values.

**Seeds can be achromatic.** `dark` or `light` instead of a hex, for a team
with no hue at all. Jaguar is now black and white, which is both true to the
brand and — being the only achromatic pair on the grid — the most instantly
recognisable stripe in the set. Andretti is yellow.

**The `is-yours` mark now sits in a reserved gutter** inside the page's own
inline padding, with `--mark-gutter` of clear space between it and the content.
Marked and unmarked rows keep the same left edge, so nothing shifts.

**The mark colour is a toggle**, top of the page: ink, indigo, magenta.

## 3. Editing the palette

`TEAM_COLOURS` in `app/palette.py`. Team name in lower case, then a tuple of
two seeds:

```python
TEAM_COLOURS: dict[str, tuple[str | None, str | None]] = {
    "jaguar tcs racing": ("dark", "light"),
    "andretti formula e": ("#F2C230", None),
    "nissan formula e team": ("#C3002F", "#FFFFFF"),   # example: real secondary
    "mahindra racing": ("#DC0714", None),              # example: tint secondary
}
```

Each seed is a hex (its hue is used, its lightness discarded), or `dark`, or
`light`. `None` in the second slot means derive the tint. An entry beats the
provider's value entirely. A team with no entry and no usable provider colour
falls back to a single neutral rule, which is the correct unattended outcome
for an eleventh Gen4 team.

Only the hue of a hex matters, so do not spend time picking an exact brand
value — pick something in roughly the right part of the wheel and let the clamp
do the rest.

## 4. Judge it in this order

**Section 02, team palette.** Fill in `TEAM_COLOURS` until no two teams look
alike and nothing shows `neutral`. The three genuine reds staying red is fine,
as you said; give them different secondaries if they need separating. Restart
the server after editing Python.

**The tint slider.** `--team-l-tint` at .72, .80 and .88 — how much the second
stripe should recede. Too dark and it competes with the primary; too light and
it disappears against the paper.

**Section 07, the yours mark.** The spacing is fixed, so judge the colour
question with fresh eyes. Ink first, then indigo and magenta against your
finished team palette. Watch for a mark that reads as an eleventh team rather
than as a different class of thing.

## 5. What I need back

- The finished `TEAM_COLOURS` table, or a list of team-to-colour and I will
  write it
- The tint value
- The mark colour
- Anything that broke at 360px

Then the palette is closed and step 3 is the two proof screens.
