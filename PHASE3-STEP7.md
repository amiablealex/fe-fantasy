# Phase 3, step 7 — the transfer flow

No migration, no dependency. `palette.py` stays out.

```
app/styleguide/__init__.py              confirm param, over-budget problem
app/styleguide/scoring_bridge.py        transfer diff, note wording
app/static/css/primitives.css           score position, team slot, budget, tags
app/templates/styleguide/_lineup.html   changed markers, split band, summary
app/templates/styleguide/lineup.html    budget, commit, reset, confirmations
```

```bash
cd ~/projects/fe-fantasy
tar xzf ~/fe-phase3-step7.tar.gz
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

## Fixes

**The score moved to the top right.** It was colliding with the ghost numeral,
which sits low. It also now shares an optical line with the driver's name,
which reads better across four slots. The dream-team star takes the bottom
corner the score vacated.

**The team slot has the recessed ground.** It was the only flat element left.
It stays a different class of object by geometry rather than by surface: heavy
rules top and bottom, and its band is **two equal stripes** rather than a band
with an accent — because a team pick is both cars, so the geometry states what
the pick is.

**Picker notes are dimmed and legible.** The row body drops to 45% opacity
while the note itself goes to full ink, and the note is one phrase — "Dennis
and Mortara are in your lineup", "Your team pick". Still fully tappable.

## The transfer flow

**The budget is stated at figure scale**, not as a caption: cost on the left,
available on the right, both in the display face. It decides whether an edit is
legal at all, so it cannot be a footnote.

**Changed slots are marked structurally** — a heavy ink outline and a small
**In** tag. Deliberately *not* the error colour. A transferred-in pick is the
thing you wanted, not a fault, and sharing red with broken rules would empty
red of meaning; you would no longer be able to tell a pending change from an
illegal one at a glance. Red stays for broken rules only.

**Over budget is a broken rule** and reads like one: the budget block turns and
the same error format you already have says "This costs 3 transfers and you
have 2. Put one of your original picks back."

**Commit is unmistakably one thing or the other.** Live and filled when there
is at least one change and the lineup is valid; otherwise flat, with the reason
on the button itself — "Fix the lineup first" or "No changes to commit". A
disabled control that merely looks quiet gets tapped.

**Commit opens a confirmation** listing Out then In, then the cost, using the
breakdown's heading language rather than a second one — you have already learnt
to read a heading with a figure on the right.

**Reset appears only when there are changes**, and confirms before discarding,
saying how many transfers go back into the bank.

Both confirmations are `<dialog>` like the picker: a decision is a task.

## Worth checking

- Transfers → swap two drivers and the team. Three slots should carry **In**
  tags, the budget should read 3, and commit should be disabled with the
  over-budget error.
- Put one back so the cost is 2, then commit — the summary should list exactly
  what moves.
- Scored → confirm the score and the ghost numeral no longer overlap.

## Next

The bracket, which closes Phase 3.

Commit message:

```
Add the transfer budget, change markers, commit and reset confirmations
```
