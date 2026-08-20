# Phase 3, step 13 — driver and team profiles

On `phase3-bracket`:

```bash
cd ~/projects/fe-fantasy
tar xzf ~/fe-phase3-step13.tar.gz
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

```
new       app/templates/styleguide/_profile.html
replaced  app/styleguide/__init__.py              profile routing
replaced  app/styleguide/scoring_bridge.py        driver/team profiles
replaced  app/static/css/primitives.css           table, key, infomark, picker row
replaced  app/templates/styleguide/_lineup.html   breakdown control, nav headline
replaced  app/templates/styleguide/_nav.html      venue is the headline
replaced  app/templates/styleguide/_results.html  names link to profiles
replaced  app/templates/styleguide/_results_body.html
replaced  app/templates/styleguide/lineup.html    picker row, profile sheet
```

## One table, as you asked

    R   TP │ GRP  DW  POL │ WIN  POD  PTS  FL  ±PL

You were right and my split was wrong. TP sits immediately after the round,
before the rules that explain it, so the first column scanned is the answer.
Two invariants hold: **every row's rule cells sum to its TP, and every column's
foot sums to the grand total.** I assert the second in the build.

Eleven columns fit 360px — I measured rather than assumed, and it clears with
about 150px spare.

What actually makes it readable is not the width but **suppressing zeros**.
Nine columns of "0" is noise; a faint mark for nothing lets the cells that fired
carry the page.

**Duel wins are one column** reading 0–3: three columns would each be almost
always 0 or 1 and perfectly correlated with progression. **Places gained and
lost share one signed column** — one mechanic with a sign.

A key sits beneath, using the same rule names the breakdown uses.

## Team profile

`R · car A · car B · TEAM`, exactly as you scoped it, plus the team's own
figure. Showing the halves beside their sum makes the half-sum rule explain
itself.

## Three entry points

- The **(i)** on each picker row
- The **(i)** in a pick's scored breakdown
- A **driver's name** in a results classification

All open over what is already there, and close by dropping a URL parameter — so
closing a profile opened from the picker leaves the picker exactly as it was.

## One structural change you should know about

**A picker row is now a container with two targets.** It was a single `<a>`, and
a link nested inside a link is invalid HTML and breaks keyboard navigation. The
pick area and the (i) are siblings now. Behaviour is unchanged; the markup is
not.

## Process note

I ran `pyflakes` over the route this time, and it immediately found the
`committed` bug you hit last step. It is now part of how I check these before
shipping:

```bash
pip install pyflakes
python -m pyflakes app/styleguide/*.py
```

Worth adding to your own routine before a commit — it catches exactly the class
of error that template-only testing cannot.

## Worth checking

- A driver who missed a round: the TP cell should read as absent, not zero.
- Add a column of any driver's profile by hand and check it against the foot.
- The (i) on a picker row: it should not select the driver.
- A profile opened from the picker, then closed — the picker should still be
  open on the same slot.

`SPEC-REVISIONS-PROFILE.md` carries revision note 5, the §5 sequence rule, the
new §4.2, §10 additions and the §7 HTMX note.

Commit message:

```
Add driver and team season profiles with three entry points; make the venue the
meeting headline
```
