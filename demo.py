"""Show the engine making one decision, with its ranked options.

    python demo.py                      # default: the boss fight, 800 ms
    python demo.py gauntlet             # or: duel | gauntlet | boss
    python demo.py boss --sims 10000    # fixed simulation count and search seed
    python demo.py duel --one-round-samples 8  # inspect sampled legal actions

A wall-clock budget stops at a machine-dependent simulation count, so two
timed runs never agree exactly. ``--sims`` disables clock stopping and uses a
fixed count. Together with the search seed (``--seed``, default 7) and the
scenario seed (``--scenario-seed``, default 7), unchanged code and content
reproduce the ranking table. Elapsed time and simulations per second still vary.

The one-round mode uses complete equal-sample sweeps without a clock limit.
Its values come from the existing simulator and heuristic, not a search tree
or calibrated win probabilities. Custom content uses the same loader:

    python demo.py trial --cards cards.json --scenarios scenarios.json --sims 8 --json

See docs/custom-scenario-report.md for the input and report contract.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from engine import GameState
from engine.mcts import MCTS
from game.baselines import OneRoundActionValue, one_round_decider
from game.decision_report import finish_report, load_snapshot, report_base

# Keep the injectable scenario collection used by the text example tests. Normal
# CLI use loads content only after argument validation, including custom files.
SCENARIOS: dict | None = None


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
    ap.add_argument("scenario", nargs="?", default="boss", help="default: boss")
    ap.add_argument("--cards", type=Path,
                    help="custom cards JSON; requires --scenarios")
    ap.add_argument("--scenarios", type=Path,
                    help="custom scenarios JSON; requires --cards")
    ap.add_argument("--scenario-seed", type=int, default=7,
                    help="seed for the initial hand, separate from --seed (default 7)")
    ap.add_argument("--json", action="store_true",
                    help="emit a versioned decision report as JSON")
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
    if (args.cards is None) != (args.scenarios is None):
        ap.error("--cards and --scenarios must be supplied together")
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

    content: dict = {}
    try:
        if args.cards is None and not args.json and SCENARIOS is not None:
            scenarios = SCENARIOS
        else:
            scenarios, content = load_snapshot(args.cards, args.scenarios)
    except OverflowError:
        ap.error("content: numeric value exceeds the supported floating-point range")
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        ap.error(f"content: {exc}")
    if args.scenario not in scenarios:
        ap.error(f"unknown scenario {args.scenario!r}; "
                 f"available: {', '.join(sorted(scenarios))}")
    state, deck = scenarios[args.scenario](random.Random(args.scenario_seed))
    base = (report_base(state, deck, content, args.scenario, args.scenario_seed)
            if args.json else {})

    if not args.json:
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
        if not args.json:
            show_one_round(state, args.one_round_samples, args.seed)
            return
        snapshots: list[tuple[OneRoundActionValue, ...]] = []
        receipts: list[dict] = []
        choose = one_round_decider(args.one_round_samples, on_ranking=snapshots.append,
                                   on_work=receipts.append)
        t0 = time.perf_counter()
        choose(state, random.Random(args.seed))
        dt = time.perf_counter() - t0
        rows = snapshots[-1]
        configuration = {"method": "one_round", "mode": "equal_samples",
                         "seed": args.seed,
                         "samples_per_action": args.one_round_samples,
                         "requested_budget_ms": args.budget_ms, "time_budget_ms": None,
                         "horizon_rounds": None, "exploration": None, "max_sims": None,
                         "max_transitions": None, "priors": None}
        statistics = [(row.action, row.samples, row.value_sum) for row in rows]
        report = finish_report(base, state, configuration, receipts[-1], statistics,
                               [row.action for row in rows], dt)
        print(json.dumps(report, allow_nan=False, indent=2))
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

    if args.json:
        configuration = {"method": "mcts",
                         "mode": "fixed" if args.sims is not None else "timed",
                         "seed": args.seed, "samples_per_action": None,
                         "requested_budget_ms": args.budget_ms,
                         "time_budget_ms": budget_ms,
                         "horizon_rounds": horizon, "exploration": mcts.exploration,
                         "max_sims": mcts.max_sims,
                         "max_transitions": mcts.max_transitions,
                         "priors": None}
        receipt = {"simulations": mcts.last_sims, "transitions": mcts.last_transitions,
                   "unused_transitions": mcts.last_unused_transitions,
                   "stop_reasons": list(mcts.last_stop_reasons)}
        report = finish_report(base, state, configuration, receipt,
                               mcts.last_root_statistics,
                               [row.action for row in ranked], dt)
        print(json.dumps(report, allow_nan=False, indent=2))
        return

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
