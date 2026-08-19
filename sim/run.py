"""Run the Season 12 simulation and print the report.

    PYTHONPATH=. python -m sim.run            # full report
    PYTHONPATH=. python -m sim.run --year 2026
    PYTHONPATH=. python -m sim.run --samples 2000

Reads the database, writes nothing. Redirect to a file to keep a copy alongside
whatever ruleset it argues for.
"""
from __future__ import annotations

import argparse
import time

from app.scoring.rules import CURRENT_VERSION, get_ruleset
from sim.analysis import (
    build_tables,
    question_1_qualifying_vs_race,
    question_2_places_magnitudes,
    question_3_judgement_vs_random,
    question_4_distribution,
    question_5_transfer_value,
    question_6_team_slot,
    question_7_dream_team_ties,
    score_season,
)
from sim.data import load_season


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def lineup_label(season, lineup) -> str:
    drivers = ", ".join(sorted(season.driver_label(d) for d in lineup.drivers))
    return f"{drivers} + {season.team_label(lineup.team_id)}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2026,
                        help="Season ending year. Season 12 is 2026.")
    parser.add_argument("--samples", type=int, default=500,
                        help="Random lineups to sample for question 3.")
    parser.add_argument("--seed", type=int, default=12)
    args = parser.parse_args()

    started = time.time()
    season = load_season(args.year)
    base = get_ruleset()

    complete = [r for r in season.rounds if r.has_race and r.has_qualifying]
    print(f"{season.display_name} ({season.year}) — ruleset {CURRENT_VERSION}")
    print(f"{len(season.rounds)} rounds loaded, {len(complete)} with both "
          f"qualifying and race data")
    missing = [r.round_number for r in season.rounds if not (r.has_race and r.has_qualifying)]
    if missing:
        print(f"  incomplete rounds excluded from conclusions: {missing}")

    scored = score_season(season, base)
    tables = build_tables(season, scored, base)

    issues = [(item.round_number, i) for item in scored for i in item.scores.issues]
    if issues:
        print(f"\n{len(issues)} scoring issues reported:")
        for round_number, issue in issues[:20]:
            print(f"  R{round_number}: {issue}")
        if len(issues) > 20:
            print(f"  ... and {len(issues) - 20} more")

    # --- 1 -------------------------------------------------------------------
    rule("1. Is qualifying dominating the race?")
    q1 = question_1_qualifying_vs_race(scored)
    print(f"  qualifying distributed: {q1['qualifying_total']:.0f}")
    print(f"  race distributed:       {q1['race_total']:.0f}")
    print(f"  race share of all points: {q1['race_share']:.1%}")
    print(f"  mean race points per round: {q1['mean_race_per_round']:.1f} "
          f"(qualifying is 26 by construction)")
    print("\n  round   quali    race   race share")
    for row in q1["per_round"]:
        print(f"  {row['round']:>5}  {row['qualifying']:>6.0f}  {row['race']:>6.0f}"
              f"   {row['race_share']:>6.1%}")

    # --- 2 -------------------------------------------------------------------
    rule("2. What are the right magnitudes for places gained/lost?")
    q2 = question_2_places_magnitudes(season, base)
    print(f"  driver-rounds scored: {q2['rows_scored']}")
    print(f"  with a places component: {q2['rows_with_places']} "
          f"({q2['share_with_places']:.1%})")
    print(f"  gained {q2['gained']}, lost {q2['lost']}, "
          f"mean magnitude {q2['mean_magnitude']:.2f}")
    print("\n  variant                     stdev   distinct   mean")
    for variant in q2["variants"]:
        print(f"  {variant['label']:<24} {variant['stdev']:>7.2f} "
              f"{variant['distinct_scores']:>9} {variant['mean']:>6.2f}")
    print("\n  Higher stdev and more distinct values mean finer resolution.")
    print("  Compare 'disabled' against the rest: that gap is what the rule buys.")

    # --- 3 -------------------------------------------------------------------
    rule("3. Would a sensible lineup have beaten a random one?")
    q3 = question_3_judgement_vs_random(
        season, scored, base, tables, args.samples, args.seed
    )
    if "error" in q3:
        print(f"  {q3['error']}")
    else:
        print(f"  valid lineups: {q3['all_lineups']}, sampled {q3['samples']}")
        print(f"  random:    mean {q3['random_mean']:.1f}, "
              f"sd {q3['random_stdev']:.1f}, "
              f"range {q3['random_min']:.0f} to {q3['random_max']:.0f}")
        print(f"  consensus: {q3['consensus_total']:.1f} "
              f"— beats {q3['consensus_percentile']:.1%} of random lineups")
        print(f"    {lineup_label(season, q3['consensus_lineup'])}")
        print(f"  best fixed lineup: {q3['best_fixed_total']:.1f}")
        print(f"    {lineup_label(season, q3['best_fixed_lineup'])}")
        print("\n  If the consensus lineup does not clear ~90%, the scoring is not")
        print("  rewarding judgement enough to be worth playing.")

    # --- 4 -------------------------------------------------------------------
    rule("4. What does the score distribution look like?")
    q4 = question_4_distribution(scored)
    print("  round    mean  median    min    max   stdev   <=0")
    for row in q4["per_round"]:
        print(f"  {row['round']:>5}  {row['mean']:>6.1f}  {row['median']:>6.1f}"
              f"  {row['min']:>5.0f}  {row['max']:>5.0f}  {row['stdev']:>6.2f}"
              f"  {row['zero_or_less']:>4}")
    print(f"\n  season driver totals: leader {q4['season_leader']:.0f}, "
          f"median {q4['season_median']:.0f}, last {q4['season_last']:.0f}, "
          f"sd {q4['season_stdev']:.1f}")

    # --- 5 -------------------------------------------------------------------
    rule("5. How much would the transfer bank have mattered?")
    q5 = question_5_transfer_value(season, scored, base, tables)
    print(f"  best single lineup, never transfers: {q5['never_transfers']:.1f}")
    print(f"    {lineup_label(season, q5['never_transfers_lineup'])}")
    print(f"  greedy transfers (hindsight, myopic): {q5['greedy_total']:.1f}")
    print(f"  gain from transferring: {q5['transfer_gain']:+.1f}")
    print(f"  unconstrained ceiling (fresh lineup every meeting): "
          f"{q5['unconstrained_total']:.1f}")
    print(f"  headroom the transfer rule denies: {q5['headroom_unused']:.1f}")
    print("\n  meeting                  spent  bank  score")
    for move in q5["greedy_moves"]:
        print(f"  {move['meeting']:>2}. {move['name']:<20} {move['spent']:>5} "
              f"{move['available_after']:>5}  {move['score']:>6.1f}")

    # --- 6 -------------------------------------------------------------------
    rule("6. Does the team slot pull its weight?")
    q6 = question_6_team_slot(season, scored, base)
    print(f"  driver round scores: mean {q6['driver_mean']:.2f}, "
          f"sd {q6['driver_stdev']:.2f}")
    print(f"  team round scores:   mean {q6['team_mean']:.2f}, "
          f"sd {q6['team_stdev']:.2f}")
    print(f"  team pick was the weakest of the five in "
          f"{q6['team_weakest_in_dream_team']} of {q6['rounds']} dream teams")

    # --- 7 -------------------------------------------------------------------
    rule("7. How often does the dream team tie?")
    q7 = question_7_dream_team_ties(season, scored, base)
    print(f"  rounds with a tied dream team: {q7['rounds_tied']} of {q7['rounds']}")
    print(f"  mean tied lineups per round: {q7['mean_tied_lineups']:.1f}, "
          f"max {q7['max_tied_lineups']}")
    print("\n  round   total   tied  best lineup")
    for row in q7["per_round"]:
        print(f"  {row['round']:>5}  {row['total']:>6.1f}  {row['tied_lineups']:>5}"
              f"  {lineup_label(season, row['best'])}")

    print(f"\nDone in {time.time() - started:.1f}s.")


if __name__ == "__main__":
    main()
