"""Payload sanity checks.

A completed session that returns a partial classification is the failure mode
worth catching: nothing errors, the rows land, and a driver quietly scores zero
for a race they finished. Comparing the provider's own championship points
against the published distribution catches it cheaply.

Season-scoped on purpose. From Season 13 Formula E awards championship points in
qualifying too, so the Season 12 expectation would produce a false failure on
every Season 13 round. See SPEC.md Appendix A.
"""
from __future__ import annotations

from decimal import Decimal

from app.models.calendar import STAGE_RACE

# Season 12 and earlier: the top ten score on this ladder.
CHAMPIONSHIP_POINTS_BY_POSITION = {
    1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1,
}
POLE_BONUS = 3
FASTEST_LAP_BONUS = 1
# Formula E awards its own fastest-lap point only inside the top ten. The
# fantasy rule in SPEC.md §3 deliberately differs; this constant describes the
# real championship, which is what the payload reports.
FASTEST_LAP_MAX_POSITION = 10

# The first season in which qualifying awards championship points, which breaks
# the expectation above.
FIRST_QUALIFYING_POINTS_SEASON_YEAR = 2027


def expected_championship_points(row, pole_driver_id: str | None = None) -> Decimal:
    """What the provider's `points` should read for a race result row.

    Pole is the Qual Final winner, NOT whoever starts P1: a grid penalty moves
    the pole sitter back while they keep the point. Sao Paulo 2025 is the case
    in point — Wehrlein took pole, started P4, and scored 15 rather than 12.
    """
    total = CHAMPIONSHIP_POINTS_BY_POSITION.get(row.position, 0)
    if pole_driver_id and row.driver is not None and row.driver.id == pole_driver_id:
        total += POLE_BONUS
    if row.fastest_lap_rank == 1 and (row.position or 999) <= FASTEST_LAP_MAX_POSITION:
        total += FASTEST_LAP_BONUS
    return Decimal(total)


def verify_championship_points(
    season_year: int, stage: str, rows: list, pole_driver_id: str | None = None
) -> list[str]:
    """Return a list of discrepancies. Empty means the payload looks complete.

    Reported as warnings rather than refusals: a mismatch means the data is
    worth a look, not that it should be thrown away.

    When the pole sitter is unknown — qualifying not ingested yet — a row may
    legitimately carry the pole bonus, so both totals are accepted rather than
    inventing a complaint.
    """
    if stage != STAGE_RACE:
        return []
    if season_year >= FIRST_QUALIFYING_POINTS_SEASON_YEAR:
        return []
    if not rows:
        return []
    if all(row.points is None for row in rows):
        return ["no championship points on any row; payload may be incomplete"]

    problems: list[str] = []
    for row in rows:
        if row.points is None:
            continue
        expected = expected_championship_points(row, pole_driver_id)
        acceptable = {expected}
        if pole_driver_id is None:
            acceptable.add(expected + POLE_BONUS)
        if Decimal(row.points) not in acceptable:
            label = row.driver.last_name if row.driver else "unknown"
            problems.append(
                f"{label} P{row.position}: points {row.points}, expected {expected}"
            )

    if len(problems) > len(rows) // 2:
        return [
            f"{len(problems)} of {len(rows)} rows disagree with the "
            "championship points distribution; the expectation may need revising"
        ]
    return problems
