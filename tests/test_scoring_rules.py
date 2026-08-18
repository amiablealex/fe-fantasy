"""The scoring ruleset is data, not behaviour, but two properties matter."""
from __future__ import annotations

import pytest

from app.scoring import rules


def test_ruleset_lookup_defaults_to_current():
    assert rules.get_ruleset().version == rules.CURRENT_VERSION


def test_unknown_ruleset_version_raises_rather_than_falling_back():
    """A round recorded against a missing version is a bug that must be loud."""
    with pytest.raises(KeyError):
        rules.get_ruleset("v99-does-not-exist")


def test_scoring_module_does_not_import_flask_or_sqlalchemy():
    """SPEC.md §12: sim/ must be able to import this without a web app."""
    import inspect

    source = inspect.getsource(rules)
    assert "flask" not in source.lower()
    assert "sqlalchemy" not in source.lower()


def test_qualifying_gradient_matches_the_spec():
    q = rules.get_ruleset().qualifying
    pole = q.group_progress + 3 * q.duel_win + q.pole
    lost_final = q.group_progress + 2 * q.duel_win
    lost_semi = q.group_progress + q.duel_win
    lost_qf = q.group_progress
    assert (pole, lost_final, lost_semi, lost_qf) == (8, 4, 3, 2)


def test_race_ceiling_matches_the_spec():
    r = rules.get_ruleset().race
    win_from_the_back = r.win + r.podium + r.points_finish + r.fastest_lap + r.places_gained_cap
    assert win_from_the_back == 17
