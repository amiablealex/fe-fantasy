"""The two decisions the weekend route makes on its own.

Both are pure functions, deliberately lifted out of the view so they can be
tested without a database, a season or a signed-in user. Everything else on that
page is a read that `queries` and `view` already cover.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.meetings.routes import _subject, default_sequence


@dataclass
class _Ref:
    sequence: int


REFS = [_Ref(1), _Ref(2), _Ref(3)]


def test_opens_on_the_latest_scored_weekend():
    """The weekend with a number against your name is the one you came for."""
    assert default_sequence(REFS, 2, 3) == 2


def test_falls_back_to_the_open_weekend_before_the_season_starts():
    """Nothing has been scored, so the only thing to show is what is next."""
    assert default_sequence(REFS, None, 1) == 1


def test_falls_back_to_the_first_weekend_when_every_deadline_has_passed():
    """A synced season with no scores and no open meeting is an unraced or
    abandoned calendar; the opener is still the honest entry point."""
    assert default_sequence(REFS, None, None) == 1


def test_no_meetings_means_no_sequence_rather_than_an_index_error():
    assert default_sequence([], None, None) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("d123", ("d", 123)),
        ("t7", ("t", 7)),
        ("", (None, None)),
        (None, (None, None)),
        ("d", (None, None)),
        ("x9", (None, None)),
        ("dabc", (None, None)),
        ("d-1", (None, None)),
    ],
)
def test_subject_parses_or_declines(raw, expected):
    """A profile parameter is reader-supplied and the two prefixes are the whole
    vocabulary. An unrecognised one is a truncated link, not an error worth a
    page."""
    assert _subject(raw) == expected
