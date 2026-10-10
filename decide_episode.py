"""Obtain a fresh fixed-work decision from one saved pre-action episode state."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from game.episode_decision import (
    DecisionRuntimeError,
    episode_decision,
    episode_stability,
)
from game.episode_inspection import extract_stability_decision
from game.episode_record import EpisodeInputError, output_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Decide from one saved pre-action state with a fresh search seed. "
                    "Emits JSON without replaying the episode.")
    parser.add_argument("record", type=Path, help="saved episode JSON")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--stability", action="store_true",
                      help="diagnose a bounded seed/coefficient grid with 64 sims "
                           "per cell")
    mode.add_argument("--extract-cell", type=int,
                      help="passively extract completed stability cell 0..47")
    parser.add_argument("--step", type=int,
                        help="zero-based existing pre-action step (0..29)")
    parser.add_argument("--seed", type=int,
                        help="new signed 64-bit search seed (default: 7)")
    parser.add_argument("--sims", type=int,
                        help="fixed simulations, 0..64 (default: 16)")
    parser.add_argument("--horizon", type=int,
                        help="simulated rounds per simulation, 1..8 (default: 4)")
    parser.add_argument("--exploration", type=float, choices=(0.6, 1.2, 2.4),
                        help="explicit single-decision coefficient; emits schema 2")
    parser.add_argument("--final-action-rule", choices=("mean_visits", "visits_mean"),
                        help="explicit single/extracted report rule; emits schema 2")
    parser.add_argument("--seeds", type=int, nargs="+",
                        help="stability only: 2..16 distinct signed seeds with "
                             "unique magnitudes")
    parser.add_argument("--explorations", type=float, nargs="+",
                        choices=(0.6, 1.2, 2.4),
                        help="stability only: unique coefficient subset "
                             "(default: all three)")
    args = parser.parse_args(argv)
    if args.extract_cell is not None:
        if any(value is not None for value in (
                args.step, args.seed, args.sims, args.horizon, args.exploration,
                args.seeds, args.explorations)):
            parser.error("--extract-cell cannot accept search/state selection controls")
    elif args.stability:
        if args.step is None or args.seeds is None:
            parser.error("--stability requires --step and --seeds")
        if (args.seed is not None or args.exploration is not None
                or args.final_action_rule is not None or args.sims not in (None, 64)):
            parser.error("--stability uses both rules and exactly 64 sims; "
                         "use --seeds/--explorations")
    else:
        if args.step is None:
            parser.error("the following arguments are required: --step")
        if args.seeds is not None or args.explorations is not None:
            parser.error("--seeds and --explorations require --stability")
    try:
        if args.extract_cell is not None:
            report = extract_stability_decision(
                args.record, cell_index=args.extract_cell,
                final_action_rule=args.final_action_rule or "mean_visits")
        elif args.stability:
            report = episode_stability(
                args.record, step=args.step, seeds=args.seeds,
                explorations=args.explorations,
                horizon=4 if args.horizon is None else args.horizon)
        else:
            report = episode_decision(
                args.record, step=args.step, seed=7 if args.seed is None else args.seed,
                sims=16 if args.sims is None else args.sims,
                horizon=4 if args.horizon is None else args.horizon,
                exploration=args.exploration, final_action_rule=args.final_action_rule)
        rendered = output_bytes(report)
        written = sys.stdout.buffer.write(rendered)
        if written != len(rendered):
            raise DecisionRuntimeError("output sink accepted an incomplete report")
        sys.stdout.buffer.flush()
        if report["status"] == "incomplete":
            print("episode decision: incomplete sweep: " + report["failure"]["message"],
                  file=sys.stderr)
            return 130 if report["failure"]["interrupted"] else 1
    except EpisodeInputError as exc:
        parser.error(str(exc))
    except (RuntimeError, OSError, ValueError, TypeError, ArithmeticError,
            RecursionError, MemoryError) as exc:
        print(f"episode decision: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("episode decision: interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    exit_status = main()
    if exit_status in (1, 130):
        # Stop interpreter shutdown from retrying a failed buffered output sink.
        try:
            sys.stdout.close()
        except OSError:
            pass
    raise SystemExit(exit_status)
