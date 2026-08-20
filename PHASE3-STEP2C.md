# Phase 3, step 2c — palette, closed

Same branch, debug-only, no migration, no dependency. Five files replaced.

```bash
cd ~/projects/fe-fantasy
tar xzf ~/fe-phase3-step2c.tar.gz
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

Hard-refresh on the phone; the CSS filenames have not changed.

## Settled from your feedback

- Tint at `0.88`, in `tokens.css`
- The yours mark stays ink; the toggle is gone
- Stripe gap defaults to `0`, so the pair reads as one banded rule

## Three fixes

**Lightness now follows the hue.** Yellows through cyans (hue 60–250) take a
lighter clamp; everything else keeps the original. This is routed automatically
from the seed — you never touch it. Your `#FFEE8C` was rendering as `#857500`,
an olive brown, because no yellow exists at lightness 0.56: the sRGB gamut tops
out around 0.118 chroma at that hue. It now renders as a real yellow.

**A `None` primary keeps the provider's colour.** So Lola gets its derived blue
and your hand-picked yellow secondary:

```python
"lola yamaha abt formula e team": (None, "#FFCC00"),
```

**The styleguide now tells you when the table is wrong.** Two panels above the
swatches:

- *Override keys matching no team*, with every real name listed so you can copy
  the right one. `"mahindra formula e team"` matches nothing — the team is
  `MAHINDRA RACING`, and until now that failed silently.
- *Hues too close to tell apart*, in degrees. Your Nissan `#FF7F7F` and Mahindra
  `#F01E2C` are 4.2° apart and render as the same colour. You cannot catch this
  by comparing hex values, because the clamp discards exactly the lightness
  difference that makes them look distinct in an editor.

Each swatch now shows its resolved **hue in degrees** rather than the raw hex.
That degree is the only number that matters and the one collisions are measured
in.

## Two controls left

Stripe gap (0, 1, 2px) and stripe width (2, 3, 4px). Both are live, both write
to one token.

## Working method

Open section 02, and work only from the two warning panels. Fix every unmatched
key, then separate every reported collision, then stop. When both panels are
empty the palette is done — no eyeballing required.

For a collision, move one of the two hues by at least 20°, or give the pair
different secondaries, or make one achromatic. Only the hue matters, so do not
hunt for exact brand values.

## What I need back

The finished `TEAM_COLOURS` table, plus the gap and width values. That closes
the palette and step 3 is the two proof screens.
