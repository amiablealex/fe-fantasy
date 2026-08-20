# Phase 3, step 3 — the two proof screens

Same branch, debug-only, no migration, no dependency.

**`tokens.css` and `palette.py` are deliberately not in this tarball**, because
they carry your palette edits. The three snippet changes from step 2c are
already folded into the files that are here.

```
new       app/styleguide/scoring_bridge.py
new       app/templates/styleguide/_shell.html
new       app/templates/styleguide/meeting.html
new       app/templates/styleguide/picker.html
replaced  app/styleguide/__init__.py
replaced  app/templates/styleguide/index.html   (now extends the shell)
replaced  app/static/css/primitives.css         (five new components)
replaced  app/static/css/styleguide.css         (page nav)
```

```bash
cd ~/projects/fe-fantasy
tar xzf ~/fe-phase3-step3.tar.gz
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

Three pages now, with a nav across the top: **Tokens**, **Meeting**, **Picker**.

## What the screens are

Both are proof screens, not the real views. Phase 4 stores real lineups; until
then both use a stand-in lineup picked deliberately across the field — four
drivers from four different teams at intervals through the roster — so the
breakdown shows a strong round, a weak one and something negative rather than
five variations on a podium.

**Meeting** opens on Berlin, a double-header, so there are two rounds stacked
under one weekend total. The meeting selector at the top switches between all
eleven. Every number on the page comes from your engine: `score_round`,
`score_team` and `dream_team`, called through the new adapter.

**Picker** is the Phase 4 interaction prototyped. Selecting drivers marks
teammates unavailable rather than hiding them, the transfer cost updates live
against the committed lineup, and constraint violations appear as sentences.
The rules are mirrored in about forty lines of JavaScript because a staged
draft needs immediate feedback; the server revalidates on commit, and the
client check is never authority.

## What to look for

**Meeting screen.** This is the densest surface in the app.

- Five picks, each with up to seven rules, twice over for a double-header. Does
  it hold at 360px, or does it become a wall?
- The two rounds are labelled by format, never "Race 1 / Race 2" — from Season
  13 they are genuinely different events.
- Picks are ordered by score within a round, so the good ones surface. Try
  meeting 8 (Sanya, the low-scoring one) against meeting 6.
- The star marks a pick that made the dream team. Round 17 has an
  eighteen-lineup tie, which is where the tie wording gets tested — that is
  meeting 11.
- One `.slab` per screen, deliberately: two big totals would compete.

**Picker screen.**

- Twenty rows of driver, number, team stripes and rounds participated. Scannable
  at 12px, or too tight?
- Tap a driver and watch their teammate dim. Tap four from four teams, then try
  the team slot of a constructor you already hold — that is the forced
  relocation, and the cost should read 2.
- The sticky slot summary keeps the running cost visible while you scroll. Does
  it eat too much of a phone screen?
- Selection uses the same structural language as `is-yours`: full ink, heavier
  weight, a rule in the gutter. No colour anywhere in the selection state.

## New primitives

`.round-head`, `.slab`, `.star`, `.option`, `.slots`, `.problem`. All in
`primitives.css`, all reading semantic tokens only. If any of them feels wrong,
it is cheaper to fix now than after Phase 4 builds on it.

## Note on the adapter

`scoring_bridge.py` sits between the ORM and the engine's plain-dict contract.
It lives under `app/styleguide/` because the proof screens are its only caller
today, but **Phase 5 promotes it to `app/meetings/` unchanged** — the scoring
worker needs exactly this translation, and writing it twice is how the two
quietly disagree. It scores nothing itself.

## What I need back

- Does the meeting breakdown hold at 360px, and at a double-header
- Does the picker feel usable, particularly the blocked-teammate state
- Any primitive that feels wrong before Phase 4 depends on it

Then the bracket, which is the last piece of Phase 3.
