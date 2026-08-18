"""Scoring rulesets.

Point values live here rather than in `app/config.py` for a specific reason
(SPEC.md §3, §7): config holds values where only the *current* value matters,
but a completed round must keep scoring the way it scored at the time. So a
ruleset is a named, versioned, frozen object, and the version in force is
recorded against each Round when the round is created.

Two consequences worth stating:

  - Changing a value below never rewrites history. It defines how *future*
    rounds score. Tuning after the Season 12 simulation, and again after
    Jeddah, is expected and safe.
  - Rescoring is idempotent: rescore a round against its recorded ruleset and
    you get the same numbers back.

This module imports nothing. That is deliberate — `sim/` imports it directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class QualifyingRules:
    """Group stage of 2 groups; top 4 of each reach the Duels bracket."""

    group_progress: int = 2
    duel_win: int = 1          # each of quarter-final, semi-final, final
    pole: int = 3

    # Resulting gradient: pole 8, lost final 4, lost semi 3, lost QF 2,
    # group exit 0. Total distributed per round across the field: 26.


@dataclass(frozen=True)
class RaceRules:
    """Race scoring. All of these stack — a win is 5 + 5 + 2 = 12 before
    fastest lap and places gained."""

    win: int = 5
    podium: int = 5
    points_finish: int = 2     # top ten
    fastest_lap: int = 1

    # Fastest lap is UNCONDITIONAL here. Formula E awards its championship
    # fastest-lap point only to a top-ten finisher; this game does not apply
    # that condition. Derive from `fastestLap.rank == 1` on the result row,
    # never from the `points` field.

    # Places gained / lost. Ships in v1 because it is the only rule that
    # resolves the midfield: without it, P4 through P10 all score 2 and seven
    # consecutive finishing positions are indistinguishable.
    #
    # Structurally asymmetric by design — a front-row qualifier has no upside
    # and up to -4 of exposure; a back-row qualifier has +4 of upside and no
    # risk. Magnitudes are provisional and are the primary output of the
    # Season 12 simulation (SPEC.md §9).
    places_step: int = 5           # one increment per 5 places
    places_gained_per_step: int = 2
    places_lost_per_step: int = 2
    places_gained_cap: int = 4
    places_lost_cap: int = 4


@dataclass(frozen=True)
class TeamRules:
    """The team pick scores half the sum of its two drivers' round scores,
    including any negative places-lost values.

    Halves are permitted and are stored as decimals — drivers on 8 and 3 give
    the team 5.5. Rounding introduces a bias that then needs explaining, so
    there is none.
    """

    divisor: Decimal = Decimal("2")


@dataclass(frozen=True)
class ScoringRuleset:
    version: str
    description: str
    qualifying: QualifyingRules
    race: RaceRules
    team: TeamRules


# -----------------------------------------------------------------------------
# Rulesets
# -----------------------------------------------------------------------------

V1_PROVISIONAL = ScoringRuleset(
    version="v1-provisional",
    description=(
        "Initial values from SPEC.md §3. Untuned. Superseded once the Season 12 "
        "simulation lands; re-tuned again after the first E-Prix Unleashed race "
        "at Jeddah, since Season 12 contains no sprint races."
    ),
    qualifying=QualifyingRules(),
    race=RaceRules(),
    team=TeamRules(),
)

RULESETS: dict[str, ScoringRuleset] = {
    V1_PROVISIONAL.version: V1_PROVISIONAL,
}

CURRENT_VERSION = V1_PROVISIONAL.version


def get_ruleset(version: str | None = None) -> ScoringRuleset:
    """Return a ruleset by version, defaulting to the current one.

    Raises rather than falling back: a round recorded against a version that no
    longer exists is a bug that must be visible, not silently rescored against
    different values.
    """
    key = version or CURRENT_VERSION
    try:
        return RULESETS[key]
    except KeyError:
        raise KeyError(
            f"Unknown scoring ruleset {key!r}. Known versions: {sorted(RULESETS)}"
        ) from None
