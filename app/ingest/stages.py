"""Deriving a session's bracket stage from its name.

All nine qualifying sessions share `type: "qualifying"`, so the only way to tell
a group stage from a final is the name — and the provider's names are not a
contract. They are matched defensively here: lowercased, punctuation flattened,
substring tested.

The asymmetry that matters: an unrecognised *qualifying* session raises, because
silently skipping one would corrupt scoring with no visible error — a driver
would simply not receive points they earned. An unrecognised session of any
other type is recorded as `other` and ignored, because Season 13 adds a
shakedown day and inventing a failure for it would be worse than useless.

No Flask, no SQLAlchemy. Pure string handling, so it is trivially testable.
"""
from __future__ import annotations

import re

from app.models.calendar import (
    SESSION_TYPE_OTHER,
    SESSION_TYPE_PRACTICE,
    SESSION_TYPE_QUALIFYING,
    SESSION_TYPE_RACE,
    STAGE_FINAL,
    STAGE_GROUP,
    STAGE_OTHER,
    STAGE_PRACTICE,
    STAGE_QUARTER_FINAL,
    STAGE_RACE,
    STAGE_SEMI_FINAL,
)

# Expected shape of a complete qualifying bracket: two groups, four
# quarter-finals, two semi-finals, one final.
EXPECTED_BRACKET = {
    STAGE_GROUP: 2,
    STAGE_QUARTER_FINAL: 4,
    STAGE_SEMI_FINAL: 2,
    STAGE_FINAL: 1,
}
EXPECTED_QUALIFYING_SESSION_COUNT = sum(EXPECTED_BRACKET.values())

_GROUP_LETTERS = {"a": 1, "b": 2, "c": 3, "d": 4}


class UnrecognisedQualifyingSession(ValueError):
    """A qualifying session whose name matches no known bracket stage.

    Deliberately loud. The alternative — skipping it — produces a scoring bug
    with no error anywhere.
    """


def normalise(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    "Qual Quarter-Final 1" and "QUAL  QUARTERFINAL 1" both reduce to something
    the matchers below can handle.
    """
    text = (name or "").lower()
    text = re.sub(r"[-_/]+", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _trailing_index(text: str) -> int | None:
    match = re.search(r"(\d+)\s*$", text)
    return int(match.group(1)) if match else None


def _group_index(text: str) -> int | None:
    """Groups are lettered ("Group A") but could be numbered. Handle both."""
    letter = re.search(r"group\s+([a-d])\b", text)
    if letter:
        return _GROUP_LETTERS[letter.group(1)]
    return _trailing_index(text)


def derive_stage(name: str, session_type: str) -> tuple[str, int | None]:
    """Return (stage, stage_index) for a session.

    Raises UnrecognisedQualifyingSession for a qualifying session that matches
    nothing. Never raises for any other type.
    """
    text = normalise(name)

    if session_type == SESSION_TYPE_PRACTICE:
        return STAGE_PRACTICE, _trailing_index(text)
    if session_type == SESSION_TYPE_RACE:
        return STAGE_RACE, None
    if session_type != SESSION_TYPE_QUALIFYING:
        # Includes `other`, and anything the provider invents later.
        return STAGE_OTHER, None

    # Order matters: "quarter final" and "semi final" both contain "final".
    if "quarter" in text:
        return STAGE_QUARTER_FINAL, _trailing_index(text)
    if "semi" in text:
        return STAGE_SEMI_FINAL, _trailing_index(text)
    if "group" in text:
        return STAGE_GROUP, _group_index(text)
    if "duel" in text:
        # Not observed, but a plausible rename of the knockout rounds. Treat a
        # bare "duel" as a quarter-final only if it carries an index that fits;
        # otherwise fall through and fail loudly rather than guess.
        index = _trailing_index(text)
        if index is not None and 1 <= index <= EXPECTED_BRACKET[STAGE_QUARTER_FINAL]:
            return STAGE_QUARTER_FINAL, index
    if "final" in text:
        return STAGE_FINAL, None

    raise UnrecognisedQualifyingSession(
        f"Qualifying session {name!r} matches no known bracket stage. "
        "Scoring would silently lose points for it, so the sync stops here."
    )


def bracket_shape(stages: list[str]) -> dict[str, int]:
    """Count sessions per stage, for comparison against EXPECTED_BRACKET."""
    counts: dict[str, int] = {}
    for stage in stages:
        counts[stage] = counts.get(stage, 0) + 1
    return counts


def bracket_is_complete(stages: list[str]) -> bool:
    counts = bracket_shape(stages)
    return all(counts.get(stage) == expected for stage, expected in EXPECTED_BRACKET.items())
