"""Obtain a fresh fixed-work decision from one saved pre-action episode state."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from game.episode_decision import DecisionRuntimeError, episode_decision
from game.episode_record import EpisodeInputError, output_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Decide from one saved pre-action state with a fresh search seed. "
                    "Emits JSON without replaying the episode.")
    parser.add_argument("record", type=Path, help="saved episode JSON")
    parser.add_argument("--step", type=int, required=True,
                        help="zero-based existing pre-action step (0..29)")
    parser.add_argument("--seed", type=int, default=7,
                        help="new signed 64-bit search seed (default: 7)")
    parser.add_argument("--sims", type=int, default=16,
                        help="fixed simulations, 0..64 (default: 16)")
    parser.add_argument("--horizon", type=int, default=4,
                        help="simulated rounds per simulation, 1..8 (default: 4)")
    args = parser.parse_args(argv)
    try:
        report = episode_decision(args.record, step=args.step, seed=args.seed,
                                  sims=args.sims, horizon=args.horizon)
        rendered = output_bytes(report)
        written = sys.stdout.buffer.write(rendered)
        if written != len(rendered):
            raise DecisionRuntimeError("output sink accepted an incomplete report")
        sys.stdout.buffer.flush()
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
