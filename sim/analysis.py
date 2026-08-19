"""The seven questions in SPEC.md §9.

Each function answers one and returns plain data; `run.py` prints it. Nothing
here decides anything — the output is evidence for a tuning conversation, not a
verdict.

One honesty note that applies throughout: every "optimal" figure below is
computed with perfect hindsight. Nobody could have picked these lineups in
advance, so they are ceilings, not expectations.
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Callable

from app.scoring.engine import (
    RULE_PLACES_GAINED,
    RULE_PLACES_LOST,
    RoundScores,
    score_round,
    score_team,
)
from app.scoring.lineups import (
    Lineup,
    dream_team,
    transfer_cost,
    valid_lineups,
)
from app.scoring.rules import ScoringRuleset, get_ruleset
from sim.data import RoundData, SeasonData


def _f(value) -> float:
    return float(value)


# -----------------------------------------------------------------------------
# Scoring the whole season
# -----------------------------------------------------------------------------


@dataclass
class ScoredRound:
    data: RoundData
    scores: RoundScores

    @property
    def round_number(self) -> int:
        return self.data.round_number

    def driver_total(self, driver_id: Any) -> Decimal:
        return self.scores.total_for(driver_id)


def score_season(
    season: SeasonData, ruleset: ScoringRuleset | None = None
) -> list[ScoredRound]:
    rules = ruleset or get_ruleset()
    out = []
    for rnd in season.rounds:
        scores = score_round(rnd.qualifying_sessions, rnd.race_rows, rules)
        out.append(ScoredRound(data=rnd, scores=scores))
    return out


def team_scores_for(
    season: SeasonData, scored: ScoredRound, ruleset: ScoringRuleset | None = None
) -> dict[int, Decimal]:
    grouped = season.drivers_by_team(scored.round_number)
    return {
        team_id: score_team(scored.scores, drivers, ruleset)
        for team_id, drivers in grouped.items()
    }


@dataclass
class SeasonTables:
    """Per-round lookup tables, computed once.

    Without this, scoring 20,160 lineups across 17 rounds rebuilds the
    team-to-driver map a third of a million times. On a Raspberry Pi that is the
    difference between a coffee and an afternoon.
    """

    rounds: list[int]
    driver_totals: dict[int, dict[Any, Decimal]]
    team_totals: dict[int, dict[Any, Decimal]]
    meeting_of_round: dict[int, int]

    def lineup_total(self, lineup: Lineup, rounds: list[int] | None = None) -> Decimal:
        total = Decimal(0)
        for round_number in rounds or self.rounds:
            drivers = self.driver_totals[round_number]
            for driver_id in lineup.drivers:
                total += drivers.get(driver_id, Decimal(0))
            total += self.team_totals[round_number].get(lineup.team_id, Decimal(0))
        return total


def build_tables(
    season: SeasonData, scored: list[ScoredRound], ruleset: ScoringRuleset
) -> SeasonTables:
    driver_totals: dict[int, dict[Any, Decimal]] = {}
    team_totals: dict[int, dict[Any, Decimal]] = {}
    meeting_of_round: dict[int, int] = {}

    for item in scored:
        rn = item.round_number
        meeting_of_round[rn] = item.data.meeting_sequence
        driver_totals[rn] = {
            driver_id: score.total for driver_id, score in item.scores.drivers.items()
        }
        team_totals[rn] = team_scores_for(season, item, ruleset)

    return SeasonTables(
        rounds=[item.round_number for item in scored],
        driver_totals=driver_totals,
        team_totals=team_totals,
        meeting_of_round=meeting_of_round,
    )


# -----------------------------------------------------------------------------
# 1. Is qualifying dominating the race?
# -----------------------------------------------------------------------------


def question_1_qualifying_vs_race(scored: list[ScoredRound]) -> dict:
    rows = []
    for item in scored:
        quali = _f(item.scores.qualifying_points_distributed)
        race = _f(item.scores.race_points_distributed)
        rows.append({
            "round": item.round_number,
            "qualifying": quali,
            "race": race,
            "race_share": race / (quali + race) if (quali + race) else 0.0,
        })
    quali_total = sum(r["qualifying"] for r in rows)
    race_total = sum(r["race"] for r in rows)
    return {
        "per_round": rows,
        "qualifying_total": quali_total,
        "race_total": race_total,
        "race_share": race_total / (quali_total + race_total) if rows else 0.0,
        "mean_race_per_round": statistics.mean(r["race"] for r in rows) if rows else 0,
    }


# -----------------------------------------------------------------------------
# 2. Magnitudes for places gained and lost
# -----------------------------------------------------------------------------


PLACES_VARIANTS: dict[str, dict] = {
    "shipped (step 5, cap 4)": {},
    "cap 2": {"places_gained_cap": 2, "places_lost_cap": 2},
    "cap 6": {"places_gained_cap": 6, "places_lost_cap": 6},
    "step 3, cap 4": {"places_step": 3},
    "step 3, cap 6": {"places_step": 3, "places_gained_cap": 6, "places_lost_cap": 6},
    "disabled": {"places_gained_per_step": 0, "places_lost_per_step": 0},
}


def variant_ruleset(base: ScoringRuleset, **race_overrides) -> ScoringRuleset:
    if not race_overrides:
        return base
    return replace(base, race=replace(base.race, **race_overrides))


def question_2_places_magnitudes(season: SeasonData, base: ScoringRuleset) -> dict:
    shipped = score_season(season, base)

    fired = 0
    total_rows = 0
    magnitudes: list[float] = []
    for item in shipped:
        for score in item.scores.drivers.values():
            total_rows += 1
            for component in score.race:
                if component.rule in (RULE_PLACES_GAINED, RULE_PLACES_LOST):
                    fired += 1
                    magnitudes.append(_f(component.points))

    variants = []
    for label, overrides in PLACES_VARIANTS.items():
        rules = variant_ruleset(base, **overrides)
        scored = score_season(season, rules)
        totals = [
            _f(score.total)
            for item in scored for score in item.scores.drivers.values()
        ]
        # How much of the spread in driver-round scores survives.
        variants.append({
            "label": label,
            "stdev": statistics.pstdev(totals) if len(totals) > 1 else 0.0,
            "distinct_scores": len(set(totals)),
            "mean": statistics.mean(totals) if totals else 0.0,
        })

    return {
        "rows_scored": total_rows,
        "rows_with_places": fired,
        "share_with_places": fired / total_rows if total_rows else 0.0,
        "mean_magnitude": statistics.mean(abs(m) for m in magnitudes) if magnitudes else 0,
        "gained": len([m for m in magnitudes if m > 0]),
        "lost": len([m for m in magnitudes if m < 0]),
        "variants": variants,
    }


# -----------------------------------------------------------------------------
# 3. Would a sensible lineup have beaten a random one?
# -----------------------------------------------------------------------------


def _season_driver_totals(scored: list[ScoredRound]) -> dict[Any, Decimal]:
    totals: dict[Any, Decimal] = {}
    for item in scored:
        for driver_id, score in item.scores.drivers.items():
            totals[driver_id] = totals.get(driver_id, Decimal(0)) + score.total
    return totals


def _score_fixed_lineup(tables: SeasonTables, lineup: Lineup) -> Decimal:
    return tables.lineup_total(lineup)


def question_3_judgement_vs_random(
    season: SeasonData, scored: list[ScoredRound], base: ScoringRuleset,
    tables: SeasonTables, samples: int = 500, seed: int = 12,
) -> dict:
    reference_round = scored[0].round_number
    grid = season.drivers_by_team(reference_round)
    if not grid:
        return {"error": "no roster for the first round"}

    all_lineups = list(valid_lineups(grid))
    rng = random.Random(seed)
    sample = rng.sample(all_lineups, min(samples, len(all_lineups)))
    random_totals = [_f(_score_fixed_lineup(tables, lineup)) for lineup in sample]

    # "Consensus best": the four highest-scoring drivers that satisfy the
    # constraints, plus the best remaining team. What an informed player would
    # have converged on, with hindsight.
    driver_totals = _season_driver_totals(scored)
    team_of_driver = season.team_of_driver(reference_round)
    ranked = sorted(driver_totals, key=lambda d: driver_totals[d], reverse=True)

    picked: list[Any] = []
    used_teams: set[Any] = set()
    for driver_id in ranked:
        team = team_of_driver.get(driver_id)
        if team is None or team in used_teams:
            continue
        picked.append(driver_id)
        used_teams.add(team)
        if len(picked) == 4:
            break

    team_season_totals: dict[Any, Decimal] = {}
    for team_id, drivers in grid.items():
        team_season_totals[team_id] = sum(
            (score_team(item.scores, drivers, base) for item in scored), Decimal(0)
        )
    best_team = max(
        (t for t in grid if t not in used_teams),
        key=lambda t: team_season_totals[t],
        default=None,
    )

    consensus = Lineup.of(picked, best_team)
    consensus_total = _f(_score_fixed_lineup(tables, consensus))

    best_possible = max(
        ((_f(_score_fixed_lineup(tables, lineup)), lineup) for lineup in all_lineups),
        key=lambda pair: pair[0],
    )

    beaten = len([t for t in random_totals if t < consensus_total])
    return {
        "samples": len(random_totals),
        "random_mean": statistics.mean(random_totals),
        "random_stdev": statistics.pstdev(random_totals),
        "random_min": min(random_totals),
        "random_max": max(random_totals),
        "consensus_total": consensus_total,
        "consensus_percentile": beaten / len(random_totals) if random_totals else 0.0,
        "consensus_lineup": consensus,
        "best_fixed_total": best_possible[0],
        "best_fixed_lineup": best_possible[1],
        "all_lineups": len(all_lineups),
    }


# -----------------------------------------------------------------------------
# 4. What does the score distribution look like?
# -----------------------------------------------------------------------------


def question_4_distribution(scored: list[ScoredRound]) -> dict:
    per_round = []
    for item in scored:
        totals = [_f(s.total) for s in item.scores.drivers.values()]
        if not totals:
            continue
        per_round.append({
            "round": item.round_number,
            "mean": statistics.mean(totals),
            "median": statistics.median(totals),
            "min": min(totals),
            "max": max(totals),
            "stdev": statistics.pstdev(totals),
            "zero_or_less": len([t for t in totals if t <= 0]),
            "drivers": len(totals),
        })

    season_totals = _season_driver_totals(scored)
    ordered = sorted(season_totals.values(), reverse=True)
    return {
        "per_round": per_round,
        "season_leader": _f(ordered[0]) if ordered else 0,
        "season_median": _f(statistics.median(ordered)) if ordered else 0,
        "season_last": _f(ordered[-1]) if ordered else 0,
        "season_stdev": statistics.pstdev([_f(v) for v in ordered]) if len(ordered) > 1 else 0,
    }


# -----------------------------------------------------------------------------
# 5. How much would the transfer bank have mattered?
# -----------------------------------------------------------------------------


def _meeting_score(
    tables: SeasonTables, round_numbers: list[int], lineup: Lineup
) -> Decimal:
    return tables.lineup_total(lineup, round_numbers)


def question_5_transfer_value(
    season: SeasonData, scored: list[ScoredRound], base: ScoringRuleset,
    tables: SeasonTables, allowance: int = 1, max_bank: int = 2,
) -> dict:
    by_meeting: dict[int, list[ScoredRound]] = {}
    for item in scored:
        by_meeting.setdefault(item.data.meeting_sequence, []).append(item)
    meetings = [by_meeting[k] for k in sorted(by_meeting)]
    meeting_rounds = [[item.round_number for item in rounds] for rounds in meetings]

    reference_round = scored[0].round_number
    grid = season.drivers_by_team(reference_round)
    candidates = list(valid_lineups(grid))

    # Never transfers: the best single lineup for the whole season, in hindsight.
    never_best = max(
        ((_f(_score_fixed_lineup(tables, lineup)), lineup) for lineup in candidates),
        key=lambda pair: pair[0],
    )

    # Myopic greedy with hindsight: at each meeting spend what is affordable to
    # maximise *that meeting*. A lower bound on true optimal play, since it never
    # banks for a future double-header.
    current: Lineup | None = None
    available = 0
    running = Decimal(0)
    moves: list[dict] = []

    for index, rounds in enumerate(meetings):
        numbers = meeting_rounds[index]
        available = min(available + allowance, max_bank)
        if current is None:
            # Season-start grace: unlimited free edits before the first deadline.
            best = max(
                ((_meeting_score(tables, numbers, lineup), lineup)
                 for lineup in candidates),
                key=lambda pair: pair[0],
            )
            current, spent = best[1], 0
        else:
            affordable = [
                lineup for lineup in candidates
                if transfer_cost(current, lineup) <= available
            ]
            best = max(
                ((_meeting_score(tables, numbers, lineup), lineup)
                 for lineup in affordable),
                key=lambda pair: pair[0],
            )
            spent = transfer_cost(current, best[1])
            current = best[1]
        available -= spent
        running += best[0]
        moves.append({
            "meeting": index + 1,
            "name": rounds[0].data.meeting_name,
            "spent": spent,
            "available_after": available,
            "score": _f(best[0]),
        })

    # Upper bound: a fresh dream team every meeting, ignoring transfers entirely.
    unconstrained = Decimal(0)
    for numbers in meeting_rounds:
        unconstrained += max(
            _meeting_score(tables, numbers, lineup) for lineup in candidates
        )

    return {
        "never_transfers": never_best[0],
        "never_transfers_lineup": never_best[1],
        "greedy_total": _f(running),
        "greedy_moves": moves,
        "unconstrained_total": _f(unconstrained),
        "transfer_gain": _f(running) - never_best[0],
        "headroom_unused": _f(unconstrained) - _f(running),
    }


# -----------------------------------------------------------------------------
# 6. Does the team slot pull its weight?
# -----------------------------------------------------------------------------


def question_6_team_slot(
    season: SeasonData, scored: list[ScoredRound], base: ScoringRuleset
) -> dict:
    driver_round_scores: list[float] = []
    team_round_scores: list[float] = []
    weakest_slot_counts = {"team": 0, "driver": 0}

    for item in scored:
        teams = team_scores_for(season, item, base)
        team_round_scores += [_f(v) for v in teams.values()]
        driver_round_scores += [_f(s.total) for s in item.scores.drivers.values()]

    # In each round's dream team, is the team pick the weakest of the five?
    for item in scored:
        grid = season.drivers_by_team(item.round_number)
        if not grid:
            continue
        teams = team_scores_for(season, item, base)
        result = dream_team(
            grid,
            lambda d: item.scores.total_for(d),
            lambda t: teams.get(t, Decimal(0)),
            keep_all_ties=False,
        )
        picks = [_f(item.scores.total_for(d)) for d in result.best.drivers]
        team_value = _f(teams.get(result.best.team_id, Decimal(0)))
        if team_value < min(picks):
            weakest_slot_counts["team"] += 1
        else:
            weakest_slot_counts["driver"] += 1

    return {
        "driver_mean": statistics.mean(driver_round_scores) if driver_round_scores else 0,
        "driver_stdev": statistics.pstdev(driver_round_scores) if len(driver_round_scores) > 1 else 0,
        "team_mean": statistics.mean(team_round_scores) if team_round_scores else 0,
        "team_stdev": statistics.pstdev(team_round_scores) if len(team_round_scores) > 1 else 0,
        "team_weakest_in_dream_team": weakest_slot_counts["team"],
        "rounds": len(scored),
    }


# -----------------------------------------------------------------------------
# 7. How often does the dream team tie?
# -----------------------------------------------------------------------------


def question_7_dream_team_ties(
    season: SeasonData, scored: list[ScoredRound], base: ScoringRuleset
) -> dict:
    rows = []
    for item in scored:
        grid = season.drivers_by_team(item.round_number)
        if not grid:
            continue
        teams = team_scores_for(season, item, base)
        result = dream_team(
            grid,
            lambda d: item.scores.total_for(d),
            lambda t: teams.get(t, Decimal(0)),
        )
        rows.append({
            "round": item.round_number,
            "total": _f(result.total),
            "tied_lineups": len(result.lineups),
            "best": result.best,
        })

    tied = [r for r in rows if r["tied_lineups"] > 1]
    return {
        "per_round": rows,
        "rounds": len(rows),
        "rounds_tied": len(tied),
        "mean_tied_lineups": statistics.mean(r["tied_lineups"] for r in rows) if rows else 0,
        "max_tied_lineups": max((r["tied_lineups"] for r in rows), default=0),
    }
