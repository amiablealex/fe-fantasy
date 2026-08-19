"""Team colour seeds.

A narrow exception to "design tokens live in CSS, never in Python" (SPEC.md
§1). The *design* decisions — how light a team colour is, how saturated, how it
sits against the ground — are the `--team-*` tokens in `tokens.css`, and they
apply to every team by rule. What lives here is which hue belongs to which
team, which is data, plus the arithmetic needed to route a hue to the right
rule.

Each team gets two stripes. The pair roughly squares how many teams can be told
apart at a glance, which matters on a grid with four red brands.

    primary    the team's dominant identity
    secondary  a real second brand colour where one exists; otherwise a
               lighter tint of the primary, derived in CSS at no cost

A seed is one of:

    "#rrggbb"   a hex whose HUE is used; its lightness is discarded
    "dark"      achromatic dark, for a team with no hue at all
    "light"     achromatic light
    None        primary: keep the provider's colour
                secondary: derive a tint of the primary


Why lightness is not the same for every team
--------------------------------------------

An earlier version clamped every hue to one lightness so the ten teams would
carry identical visual weight. That was wrong, and yellow proved it: at
lightness 0.56 the most chroma sRGB can hold at hue 100 is 0.118, so a yellow
seed rendered as olive brown. No yellow exists at that lightness. Yellows and
cyans reach their maximum chroma light; reds and purples reach theirs dark.

So there are two clamp tiers, and the hue picks its own. Perceptual weight is
not lightness alone — a saturated yellow at 0.72 and a red at 0.56 read as
equally present, whereas forcing both to one number makes one of them mud.

The tier boundaries are here because they are arithmetic over a hue angle. The
lightness and chroma each tier applies are in `tokens.css`, where they can be
retuned without touching Python.
"""

from __future__ import annotations

import math
import re

_UNUSABLE = {"000000", "ffffff"}

ACHROMATIC = ("dark", "light")

# Below this chroma a hue angle is meaningless — the colour is a grey, and
# relative colour syntax would pick an arbitrary hue for it.
_MIN_CHROMA = 0.02

# Hues in this half-open band cannot hold the standard chroma at the standard
# lightness and take the bright tier instead: yellow through cyan into light
# blue. Verified against the sRGB gamut across the whole band.
_BRIGHT_HUE_RANGE = (60.0, 250.0)

# Two hues closer than this are not reliably distinguishable once clamped.
COLLISION_DEGREES = 15.0

# ---------------------------------------------------------------------------
# The override table. This is the file to edit.
# ---------------------------------------------------------------------------
#
# An entry beats the provider's `team.color`. Add one when the styleguide shows
# a team falling back to neutral, reports a hue collision, or when the
# provider's colour is not what you associate with that team.
#
# Keys must match a real team name, lower case. The styleguide lists any key
# that matched nothing, along with the names actually in the database.

TEAM_COLOURS: dict[str, tuple[str | None, str | None]] = {
    # Provider sends 000000. The only achromatic pair on the grid, which makes
    # it the most recognisable stripe in the set rather than the least.
    "jaguar tcs racing": ("dark", "light"),
    "andretti formula e": ("#FFEE8C", None),
    "cupra kiro": ("#895129", "light"),
    "porsche formula e team": ("#5B118B", None),
    "mahindra racing": (None, "#FF2C2C"),
    "citroën racing": (None, "dark"),
}


# ---------------------------------------------------------------------------
# Colour arithmetic
# ---------------------------------------------------------------------------


def _srgb_to_linear(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def oklch_hue_chroma(hex_colour: str) -> tuple[float, float]:
    """Hue in degrees and chroma for a `#rrggbb`.

    Matches a reference OKLCH implementation to well under a degree, and needs
    no dependency to do it.
    """
    raw = hex_colour.lstrip("#")
    r, g, b = (_srgb_to_linear(int(raw[i:i + 2], 16) / 255) for i in (0, 2, 4))

    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b

    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))

    a_ = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b_ = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_

    return math.degrees(math.atan2(b_, a_)) % 360, math.hypot(a_, b_)


def hue_distance(a: float, b: float) -> float:
    """Shortest angular distance between two hues."""
    delta = abs(a - b) % 360
    return min(delta, 360 - delta)


def _is_bright(hue: float) -> bool:
    low, high = _BRIGHT_HUE_RANGE
    return low <= hue < high


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------


def _normalise(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"\s+", " ", name).strip().lower()


def _clean_hex(value: str | None) -> str | None:
    """Return a six-digit `#rrggbb`, or None if the value has no usable hue."""
    if not value:
        return None
    raw = value.strip().lstrip("#").lower()
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    if len(raw) != 6 or not re.fullmatch(r"[0-9a-f]{6}", raw):
        return None
    if raw in _UNUSABLE:
        return None
    if oklch_hue_chroma(raw)[1] < _MIN_CHROMA:
        return None  # a grey: the hue angle would be arbitrary
    return f"#{raw}"


def _override(team) -> tuple[str | None, str | None] | None:
    for candidate in (getattr(team, "name", None), getattr(team, "short_name", None)):
        entry = TEAM_COLOURS.get(_normalise(candidate))
        if entry:
            return entry
    return None


def _resolve_primary(team) -> str | None:
    """The primary seed: override first, provider second.

    A `None` primary in an override means "keep the provider's colour" — which
    is how a team gets its real primary and a hand-picked secondary.
    """
    override = _override(team)
    if override and override[0] is not None:
        return override[0]
    return getattr(team, "color", None)


def _mark(seed: str | None, *, tint: bool = False) -> dict[str, str] | None:
    """One stripe, as the style and modifier class the template needs.

    The CSS owns every visual value; this only says which hue and which rule.
    """
    if seed in ACHROMATIC:
        return {"style": "", "modifier": f"team-mark--{seed}"}

    cleaned = _clean_hex(seed)
    if not cleaned:
        return None

    classes = []
    if _is_bright(oklch_hue_chroma(cleaned)[0]):
        classes.append("team-mark--bright")
    if tint:
        classes.append("team-mark--tint")

    return {"style": f"--team-seed: {cleaned}", "modifier": " ".join(classes)}


def team_marks(team) -> list[dict[str, str]]:
    """The stripes for a team, in order. Two, one, or none.

    An empty list means no usable seed anywhere; the template falls back to a
    single neutral rule, which is the correct unattended outcome for an
    eleventh Gen4 team.
    """
    primary_seed = _resolve_primary(team)
    primary = _mark(primary_seed)
    if primary is None:
        return []

    override = _override(team)
    secondary_seed = override[1] if override else None

    if secondary_seed is None:
        secondary = _mark(primary_seed, tint=True)
    else:
        secondary = _mark(secondary_seed)

    return [m for m in (primary, secondary) if m]


def team_hue(team) -> float | None:
    """The primary stripe's hue, or None for achromatic and unseeded teams."""
    seed = _resolve_primary(team)
    if seed in ACHROMATIC:
        return None
    cleaned = _clean_hex(seed)
    return oklch_hue_chroma(cleaned)[0] if cleaned else None


def seed_source(team) -> str:
    override = _override(team)
    if override and override[0] is not None:
        return "override"
    if _clean_hex(getattr(team, "color", None)):
        return "override (secondary)" if override else "provider"
    return "neutral"


# ---------------------------------------------------------------------------
# Diagnostics — styleguide only
# ---------------------------------------------------------------------------


def unmatched_overrides(teams) -> list[str]:
    """Override keys that match no team in the database.

    A silent no-match is the worst failure this table has: you edit it, reload,
    and nothing changes with nothing saying why.
    """
    known = set()
    for team in teams:
        known.add(_normalise(getattr(team, "name", None)))
        known.add(_normalise(getattr(team, "short_name", None)))
    return sorted(key for key in TEAM_COLOURS if key not in known)


def collisions(teams, threshold: float = COLLISION_DEGREES) -> list[tuple]:
    """Pairs of teams whose primary hues are too close to tell apart.

    Reported as (team a, team b, degrees). Comparing hex values by eye does not
    catch this, because the clamp discards exactly the lightness difference
    that makes two seeds look distinct in a code editor.
    """
    seeded = [(t, team_hue(t)) for t in teams]
    seeded = [(t, h) for t, h in seeded if h is not None]

    found = []
    for i, (team_a, hue_a) in enumerate(seeded):
        for team_b, hue_b in seeded[i + 1:]:
            delta = hue_distance(hue_a, hue_b)
            if delta < threshold:
                found.append((team_a, team_b, round(delta, 1)))
    return sorted(found, key=lambda row: row[2])
