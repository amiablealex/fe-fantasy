# Phase 3, step 5 — picker notes and legible zeros

Four files, all replacements. No migration, no dependency, nothing else
touched — `palette.py`, `tokens.css` and the other templates are deliberately
absent.

```
app/styleguide/scoring_bridge.py
app/templates/styleguide/_lineup.html
app/templates/styleguide/lineup.html
app/static/css/primitives.css
```

```bash
cd ~/projects/fe-fantasy
tar xzf ~/fe-phase3-step5.tar.gz
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

## 1. Nothing in the picker is blocked any more

Every option is tappable. Where taking one would break a rule, the row carries
a note instead:

    CITROËN RACING
    Barnard is in your lineup

You get the same warning greying gave, without the trap: a two-slot change can
now be approached from either end. Take the team first and the draft goes
invalid with commit disabled, exactly as taking the driver first already did.

One rule across the editor now: **the interface never prevents, it explains.**
Disabled controls say no; errors say what is wrong and what to do.

## 2. Zeros are legible

Both sections of a breakdown always render when the driver took part, each led
by a sentence about what happened:

    Qualifying                    0
      Eliminated in Group B P7

    Race                          0
      Started P14 · finished P13

A retirement reads `Started P1 · retired, classified P20`, which explains a
&minus;4 without needing a rule to say so. A driver genuinely absent from the
round reads "Did not take part" — which "no rules fired" could never
distinguish from qualifying fifteenth.

This is derived from the raw payload, not from the engine. Making the engine
emit zero-point components would corrupt what "which rules fired" means and
break `DriverRoundScore.fired()`, so the wording is the adapter's job — the
same division as the problem messages.

## 3. "Out of the group" is now "Reached the Duels"

Your reading was right: it sounded like elimination. This names the achievement
in Formula E's own term and cannot be misread as an exit.

## Worth checking

- Lineup → Transfers → tap the team slot. Every team is now selectable; four
  carry notes. Take the one your own driver holds and watch the error appear.
- Lineup → Scored → meeting 1 (São Paulo, seven retirements) and tap a driver
  who scored badly. The zero should now read as a result.

## Next

Step 6 is the visual pass on the lineup component — figure/ground, the team
stripe going structural, a real rule-weight hierarchy. Then the bracket, inside
the settled language.

I still need your call on one thing: when the team stripe becomes structural on
a slot, does it stay two stripes, or does the primary become the band with the
secondary as a thinner accent within it? I lean the latter at slot scale.

Commit message:

```
Replace picker blocking with notes; always show qualifying and race context in
breakdowns
```
