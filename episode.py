"""Record a bounded example episode, or replay its environment without search."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from game.episode_record import (
    MAX_HORIZON,
    MAX_ROUNDS,
    MAX_SIMS,
    SEED_MAX,
    SEED_MIN,
    EpisodeInputError,
    EpisodeRuntimeError,
    integer,
    output_bytes,
    record_episode,
    replay_episode,
)


def _bounded(low: int, high: int):
    def parse(text: str) -> int:
        try:
            return integer(int(text), "argument", low, high)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from exc
    return parse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record a bounded episode or replay its environment. Emits JSON.")
    operations = parser.add_subparsers(dest="operation", required=True)
    record = operations.add_parser("record", help="run clockless serial MCTS once")
    record.add_argument("scenario", nargs="?", default="boss")
    record.add_argument("--environment-seed", type=_bounded(SEED_MIN, SEED_MAX),
                        default=7)
    record.add_argument("--search-seed", type=_bounded(SEED_MIN, SEED_MAX), default=7)
    record.add_argument("--rounds", type=_bounded(1, MAX_ROUNDS), default=30)
    record.add_argument("--sims", type=_bounded(1, MAX_SIMS), default=16)
    record.add_argument("--horizon", type=_bounded(1, MAX_HORIZON), default=4)
    replay = operations.add_parser("replay",
                                   help="apply recorded actions without search")
    replay.add_argument("record", type=Path)
    for command in (record, replay):
        command.add_argument("--cards", type=Path, help="custom cards JSON")
        command.add_argument("--scenarios", type=Path, help="custom scenarios JSON")
    args = parser.parse_args(argv)
    if (args.cards is None) != (args.scenarios is None):
        parser.error("--cards and --scenarios must be supplied together")
    try:
        if args.operation == "record":
            value = record_episode(
                args.scenario, cards_path=args.cards, scenarios_path=args.scenarios,
                environment_seed=args.environment_seed, search_seed=args.search_seed,
                rounds=args.rounds, sims=args.sims, horizon=args.horizon)
            status = 0
        else:
            value, status = replay_episode(args.record, cards_path=args.cards,
                                          scenarios_path=args.scenarios)
        rendered = output_bytes(value)
        written = sys.stdout.buffer.write(rendered)
        if written != len(rendered):
            raise EpisodeRuntimeError("output sink accepted an incomplete JSON object")
        sys.stdout.buffer.flush()
    except EpisodeInputError as exc:
        parser.error(str(exc))
    except (RuntimeError, ValueError, OverflowError, OSError) as exc:
        print(f"episode runtime: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("episode interrupted", file=sys.stderr)
        return 130
    return status


if __name__ == "__main__":
    exit_status = main()
    if exit_status in (1, 130):
        # Retire a failed buffered sink before shutdown can retry its flush.
        try:
            sys.stdout.close()
        except (OSError, ValueError, KeyboardInterrupt):
            pass
    raise SystemExit(exit_status)
