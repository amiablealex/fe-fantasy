"""The poll's patient phase, which is stateless now the worker is a cron job.

Pure arithmetic: no app, no database. Whatever phase the cron ticks happen to
sit at relative to a session's end, the patient phase must attempt exactly
once per patient interval, starting on the first tick after the eager phase.
"""
from datetime import timedelta as td

import pytest

from worker.jobs import patient_attempt_due

EAGER = td(minutes=30)
PATIENT = td(minutes=15)
TICK = td(minutes=5)


def _fired(phase: td, ticks: int) -> list[td]:
    elapsed = [EAGER + phase + TICK * i for i in range(ticks)]
    return [e for e in elapsed if patient_attempt_due(e, EAGER, PATIENT, TICK)]


@pytest.mark.parametrize("phase_seconds", [1, 37, 120, 299])
def test_one_attempt_per_patient_interval(phase_seconds):
    fired = _fired(td(seconds=phase_seconds), ticks=36)  # three hours
    assert len(fired) == 12
    assert {b - a for a, b in zip(fired, fired[1:])} == {PATIENT}


@pytest.mark.parametrize("phase_seconds", [1, 37, 120, 299])
def test_first_patient_attempt_is_the_first_tick_after_eager(phase_seconds):
    fired = _fired(td(seconds=phase_seconds), ticks=36)
    assert fired[0] == EAGER + td(seconds=phase_seconds)
