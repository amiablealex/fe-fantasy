# Phase 3, step 2 — tokens, primitives, DB-backed styleguide

Still nothing in production. The blueprint remains debug-only.

## What changes

**New, permanent:**

```
app/static/css/tokens.css       the design system. Colour tweaks happen here.
app/static/css/primitives.css   layout + component primitives
app/palette.py                  team colour seed repair (data, not design)
```

**New, disposable:**

```
app/static/css/styleguide.css   the styleguide's own chrome
app/styleguide/queries.py       read-only queries against the S12 backfill
app/templates/styleguide/index.html
```

**Replaced:** `app/styleguide/__init__.py`

**Deleted:** the specimen, its hardcoded data, and Newsreader.

## 1. Extract

From `~/projects/fe-fantasy`, on the `phase3-typeface` branch:

```bash
cd ~/projects/fe-fantasy
tar xzf ~/fe-phase3-step2.tar.gz
```

## 2. Remove the specimen

The typeface is settled, so the losing candidate and the scaffolding that
compared them both go.

```bash
rm app/static/fonts/Newsreader.woff2
rm app/static/fonts/OFL-Newsreader.txt
rm app/static/css/specimen.css
rm app/styleguide/data.py
rm app/templates/styleguide/specimen.html
git status
```

Two font files remain: Archivo at 136 KB and Anybody at 68 KB.

## 3. Run it

No migration, no schema change, no new dependency.

```bash
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

Open `http://<pi-ip>:5000/styleguide` on the phone.

If the page says "No Season 12 data found", the app is pointing at a database
without the backfill — check `DATABASE_URL` in `.env`.

## 4. What to look at, in order

**Section 02, team palette.** This is the one that needs your judgement most,
because it is the only part of the system driven by data I cannot see.

- Any team showing `neutral` has no usable seed and needs an entry in
  `TEAM_SEED_OVERRIDES` in `app/palette.py`. I have pre-filled Jaguar and
  Andretti because the spec records both as `000000`; there may be others.
- Any two teams whose bars look like the same colour need one of them
  overridden. Ten hues is close to the limit of what anyone distinguishes, so a
  near-collision is a real problem rather than a nicety.
- If the whole set looks too washed out or too loud, that is `--team-l` and
  `--team-c` in `tokens.css`, and it is a two-number change affecting all ten
  at once. Try it — that is the payoff for having the tokens in CSS.

**The tuner at the top.** Six buttons, settling Anybody's width and weight.
Watch section 06 (the round number and venue) and section 08 (the totals). Tell
me the pair you land on and I will write it into `tokens.css` as the default.

**Section 07, race classification.** Round 1 is São Paulo, which has seven
retirements occupying P14 to P20 — the hardest round in the season for this
table. Check that six columns hold at your narrowest viewport, that the DNF
rows read as retirements without shouting, and that the two `is-yours` rows are
unmistakable without any colour.

The round buttons in section 06 switch every table on the page, so you can push
17 different rounds of real data through the same layout.

**Section 09, driver picker.** Twenty rows, each with a name, number, team and
round count. This is the layout Phase 4 builds on.

## 5. What I need back

- Teams needing an override, and any two that collide
- The Anybody width/weight pair
- Whether `--team-l` / `--team-c` want moving, and to what
- Anything that broke at 360px

Phone screenshots again, especially of section 02 and section 07.

## 6. Still no push

The branch merges to `main` at the end of Phase 3, once the bracket is solved.
Merging a half-settled design system just means restyling twice.

## Notes on how this is put together

**Two token tiers, and only two.** Primitives (`--ink-600`, `--step-3`,
`--space-4`) are named for what they are; semantics (`--text-mid`, `--rule`,
`--surface`) are named for what they do. Components read semantics and never
primitives. When a component wants a value with no semantic name, the value is
missing a name — that is the signal to add one, not to reach past the rule.

**Layer order is declared once, at the top of `tokens.css`:** reset, tokens,
base, layout, components, utilities. Later layers win regardless of selector
specificity, which is what stops the `.section` versus `.cta` margin fights that
make stylesheets unmaintainable. Anything outside a layer beats everything
inside one, so unlayered CSS is the escape hatch and should stay empty.

**Team colour is computed in the browser.** The app emits `--team-seed: #c3002f`
as an inline style and the stylesheet does
`oklch(from var(--team-seed) var(--team-l) var(--team-c) h)` — take that hex's
hue, impose our lightness and chroma. This is relative colour syntax, and it is
why the palette can be retuned without touching Python. There is an `@supports`
guard, so a browser without it falls back to the neutral rule rather than
breaking.

`app/palette.py` therefore contains no design decisions. It supplies a
substitute hue where the provider's value has none — `000000` has no hue at all,
and without the substitution both Jaguar and Andretti would resolve to hue 0 and
paint themselves red. That is data repair, and it belongs in Python. The two
numbers that decide how the palette *looks* are in CSS.

**Sizes are in `rem`.** Someone who has raised their phone's text size gets a
larger app. The single exception is form inputs, pinned at 16px in the base
layer: below that, iOS Safari zooms the viewport on focus, and every layout
decision in this file stops being true.
