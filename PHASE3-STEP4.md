# Phase 3, step 4 — the lineup component

Same branch, debug-only, no migration, no dependency.

**`palette.py` is not in this tarball** — it carries your `TEAM_COLOURS` table.
`tokens.css` *is*, because it gains the two `--error` tokens; it already has
your `--stripe-width` line folded in.

```
new       app/templates/styleguide/_lineup.html   the component, as macros
new       app/templates/styleguide/lineup.html    the three states
replaced  app/styleguide/__init__.py              routes; draft held in the URL
replaced  app/styleguide/scoring_bridge.py        aggregation, draft status, picker
replaced  app/templates/styleguide/meeting.html   now the full-results view
replaced  app/templates/styleguide/_shell.html    nav
replaced  app/static/css/tokens.css               --error, --error-recessed
replaced  app/static/css/primitives.css           lineup, slot, breakdown, dialog

deleted   app/templates/styleguide/picker.html    folded into the lineup states
```

```bash
cd ~/projects/fe-fantasy
tar xzf ~/fe-phase3-step4.tar.gz
rm app/templates/styleguide/picker.html
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

Three pages: **Tokens**, **Lineup**, **Results**.

## The route to try, in order

Open **Lineup**, and use the state buttons at the top.

1. **Empty.** Five dashed slots. Tap one — the picker opens as a real modal,
   escape closes it. Pick a driver; the slot fills and the picker closes.
2. Keep going. After the first pick, that driver's teammate is greyed with
   "Team already represented", and so is their constructor in the team list.
   That is the rule you asked for, now applied to both lists.
3. **Transfers.** Starts from the committed lineup. Tap a driver slot and pick
   someone from the constructor already in your team slot. The draft goes
   invalid: the reason appears above the component, the offending slots are
   outlined, and commit greys out. Now tap the team slot and move it — the
   error clears and the cost reads **2**. That is the forced relocation, held
   legibly rather than prevented.
4. **Scored.** One number per slot. Meeting 6 is Berlin, a double-header, so
   each total is both rounds added. Tap a slot for the breakdown: split by
   round, then Qualifying against Race. Meeting 8 is the sparse case, meeting 11
   contains the eighteen-lineup tie.

**Results** is the old meeting screen, now doing the job you described: the full
classification with your picks marked, sitting behind the lineup rather than
competing with it.

## Two decisions worth knowing

**The draft lives in the query string, not in JavaScript.** That is why every
constraint message and the transfer cost come from `app/scoring/lineups.py` —
the real rules, the ones the server enforces on commit — instead of a mirrored
copy in JavaScript that drifts. Phase 4 swaps the full reload for an HTMX
partial and keeps that property. The only JavaScript on the page is the twelve
lines that open a breakdown.

**The breakdown is a panel below the grid, not a `<details>`.** I recommended
`<details>` before seeing the geometry; a native disclosure inside a 2×2 grid
cell expands to half width and shunts the layout. The grid won.

## What to look at

- Does the 2×2 grid hold a long surname and a large figure at 360px? `Drugovich`
  and `Di Grassi` are the stress cases.
- Is the team slot obviously a different class of object without reading it?
- The error state: is the `!` glyph in its ruled square right, or does it read
  as decoration? It comes out in one line if so.
- Does one number per slot feel like enough on the scored state, or does
  something want to be visible without a tap?

`SPEC-REVISIONS.md` in this tarball has the full spec changes: revision note 4,
a rewritten §1 Design values, a new §4.1 for the component, additions to the
§10 resolved table and §12, and the `rules.py` comment fix.

Commit message:

```
Add the lineup component in three states; hold draft state in the URL so
validation stays server-side
```

Next: the bracket, which closes Phase 3.
