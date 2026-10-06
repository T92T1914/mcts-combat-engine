"""Show the engine making one decision, with its ranked options.

    python demo.py                      # default: the boss fight, 800 ms
    python demo.py gauntlet             # or: duel | gauntlet | boss
    python demo.py boss --sims 10000    # fixed simulation count and search seed
    python demo.py duel --one-round-samples 8  # inspect sampled legal actions

A wall-clock budget stops at a machine-dependent simulation count, so two
timed runs never agree exactly. ``--sims`` disables clock stopping and uses a
fixed count. Together with the search seed (``--seed``, default 7) and the
fixed scenario seed 7, unchanged code and content reproduce the ranking
table. Elapsed time and simulations per second still vary.

The one-round mode uses complete equal-sample sweeps without a clock limit.
Its values come from the existing simulator and heuristic, not a search tree
or calibrated win probabilities. The scenario still uses seed 7.
"""
from __future__ import annotations

import argparse
import random
import time

from engine import GameState
from engine.mcts import MCTS
from game.baselines import OneRoundActionValue, one_round_decider
from game.content import SCENARIOS


def positive_samples(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("sample count must be positive")
    return value


def show_one_round(state: GameState, samples: int, seed: int) -> None:
    snapshots: list[tuple[OneRoundActionValue, ...]] = []
    choose = one_round_decider(samples, on_ranking=snapshots.append)
    t0 = time.perf_counter()
    action = choose(state, random.Random(seed))
    dt = time.perf_counter() - t0
    rows = snapshots[-1]
    transitions = sum(row.samples for row in rows)
    completed = rows[0].samples if rows else 0
    print(f"\nOne-round reference: {len(rows)} actions, {completed} complete "
          f"sweeps, {transitions} sampled rounds in {dt*1000:.0f} ms")
    print("Means use the shared simulator and heuristic, not win probabilities.")
    print("Hand and target indexes are zero-based. '-' means no index.\n")
    print(f"{'move':32}{'hand':>6}{'target':>8}{'mean':>8}{'samples':>10}")
    for row in rows:
        hand = "-" if row.action.card_idx is None else str(row.action.card_idx)
        target = "-" if row.action.target_idx is None else str(row.action.target_idx)
        print(f"{row.action.describe(state):32}{hand:>6}{target:>8}"
              f"{row.mean_value:>8.3f}{row.samples:>10,}")
    if rows:
        print(f"\nRecommended: {action.describe(state)} "
              f"(hand={action.card_idx}, target={action.target_idx})")
    else:
        print("\nNo sampled actions; no recommendation is available.")


def main() -> None:
    ap = argparse.ArgumentParser(description="One search decision, ranked.")
    ap.add_argument("scenario", nargs="?", default="boss",
                    choices=sorted(SCENARIOS), help="default: boss")
    ap.add_argument("--budget-ms", type=int, default=None,
                    help="MCTS wall-clock search budget (default 800)")
    work = ap.add_mutually_exclusive_group()
    work.add_argument("--sims", type=int, default=None,
                    help="run exactly this many simulations instead of a "
                         "time budget; makes the table reproducible")
    work.add_argument("--one-round-samples", type=positive_samples, default=None,
                      help="show the one-round reference with this many samples "
                           "per legal action, without a clock limit")
    ap.add_argument("--seed", type=int, default=7,
                    help="seed for search or one-round sampling (default 7)")
    ap.add_argument("--horizon", type=int, default=None,
                    help="MCTS rollout horizon in rounds (default 6)")
    args = ap.parse_args()
    if args.one_round_samples is not None and (
            args.budget_ms is not None or args.horizon is not None):
        ap.error("--budget-ms and --horizon apply only to MCTS, "
                 "not --one-round-samples")
    if args.sims is not None and args.sims < 0:
        ap.error("--sims must be nonnegative")
    if args.horizon is not None and args.horizon < 1:
        ap.error("--horizon must be positive")
    # Fixed-count mode ignores the clock option, as it did before validation.
    if args.sims is None and args.budget_ms is not None and args.budget_ms < 0:
        ap.error("--budget-ms must be nonnegative")

    rng = random.Random(7)                  # deals the hand; fixed on purpose
    state, _ = SCENARIOS[args.scenario](rng)

    player = state.player
    print(f"Scenario: {args.scenario}")
    print(f"You: {player.name}  HP {player.hp}/{player.max_hp}  "
          f"pips {player.pips}+{player.power_pips}p")
    for e in state.enemies:
        tag = " [boss]" if e.is_boss else ""
        print(f"  vs {e.name}{tag}  HP {e.hp}/{e.max_hp}")
    print(f"Hand: {', '.join(c.name for c in state.hand)}")
    for r in state.boss_rules:
        print(f"  rule: {r.description}")

    if args.one_round_samples is not None:
        show_one_round(state, args.one_round_samples, args.seed)
        return

    horizon = 6 if args.horizon is None else args.horizon
    mcts = MCTS(horizon_rounds=horizon, rng=random.Random(args.seed))
    if args.sims is not None:
        mcts.max_sims = args.sims
        budget_ms = None
    else:
        mcts.max_sims = 1_000_000
        budget_ms = 800 if args.budget_ms is None else args.budget_ms
    t0 = time.perf_counter()
    ranked = mcts.search(state, time_budget_ms=budget_ms)
    dt = time.perf_counter() - t0

    print(f"\n{mcts.last_sims:,} simulations in {dt*1000:.0f} ms "
          f"({mcts.last_sims / dt:,.0f}/s)\n")
    print(f"{'move':32}{'reward':>8}{'visits':>10}")
    for r in ranked[:8]:
        print(f"{r.label:32}{r.win_rate:>8.3f}{r.visits:>10,}")
    if ranked:
        print(f"\nRecommended: {ranked[0].label}")
    else:
        print("\nNo simulations ran; no recommendation is available.")


if __name__ == "__main__":
    main()
