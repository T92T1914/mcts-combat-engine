"""Compute or passively inspect the companion's independent one-round report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from game.episode_record import EpisodeInputError, output_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Price a saved decision with the bounded independent one-round "
        "reference, or inspect already saved reference data."
    )
    parser.add_argument(
        "report",
        type=Path,
        help="saved decision JSON, or reference JSON with --inspect",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="emit passive self-contained HTML without calculation",
    )
    parser.add_argument(
        "--compare-report",
        type=Path,
        metavar="RIGHT",
        help="compare a second reference report with --inspect",
    )
    parser.add_argument(
        "--appearance",
        choices=("obscur", "clair"),
        help="inspection appearance (default: obscur)",
    )
    parser.add_argument(
        "--model",
        choices=("one-round", "three-enemy"),
        help="calculation subset: one-round retains one/two initial enemies "
        "(default); three-enemy explicitly requires exactly three",
    )
    parser.add_argument(
        "--method",
        choices=("physical", "sum-convolution"),
        help="calculation method: physical enumeration (default), or explicit "
        "integer sum convolution for the narrower nonlethal damage subset",
    )
    parser.add_argument(
        "--max-paths", type=int, help="leaves per action, 1..250000 (default: 250000)"
    )
    parser.add_argument(
        "--max-total-paths",
        type=int,
        help="leaves for all actions, 1..1000000 (default: 1000000)",
    )
    parser.add_argument(
        "--max-contributions",
        type=int,
        help="sum-convolution integer contribution updates for all actions, "
        "1..1000000 (default: 1000000)",
    )
    parser.add_argument(
        "--max-payoff-evaluations",
        type=int,
        help="sum-convolution source-order payoff evaluations for all actions, "
        "1..10000 (default: 10000)",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        help="cooperative deadline, 0.000001..30 for physical enumeration or "
        "finite positive at most 30 for sum-convolution "
        "(default: 30, no hard wall or memory guarantee)",
    )
    args = parser.parse_args(argv)
    if args.inspect:
        if any(
            value is not None
            for value in (
                args.model,
                args.method,
                args.max_paths,
                args.max_total_paths,
                args.max_contributions,
                args.max_payoff_evaluations,
                args.max_seconds,
            )
        ):
            parser.error("inspection cannot accept model or calculation controls")
    elif args.compare_report is not None or args.appearance is not None:
        parser.error("--compare-report and --appearance require --inspect")
    elif args.method == "sum-convolution":
        if args.max_paths is not None or args.max_total_paths is not None:
            parser.error("physical leaf controls cannot limit sum-convolution work")
    elif args.max_contributions is not None or args.max_payoff_evaluations is not None:
        parser.error(
            "contribution and payoff controls require --method sum-convolution"
        )
    try:
        if args.inspect:
            from reference.report import (
                reference_comparison_html,
                reference_inspection_html,
            )

            if args.compare_report is None:
                rendered = reference_inspection_html(
                    args.report, appearance=args.appearance or "obscur"
                )
            else:
                rendered = reference_comparison_html(
                    args.report,
                    args.compare_report,
                    appearance=args.appearance or "obscur",
                )
            exit_status = 0
        else:
            from reference.aggregation_domain import METHOD, PHYSICAL_METHOD
            from reference.consumer import reference_decision
            from reference.report import MODEL, THREE_ENEMY_MODEL

            report = reference_decision(
                args.report,
                max_paths=250_000 if args.max_paths is None else args.max_paths,
                max_total_paths=(
                    1_000_000 if args.max_total_paths is None else args.max_total_paths
                ),
                max_seconds=30.0 if args.max_seconds is None else args.max_seconds,
                model=THREE_ENEMY_MODEL if args.model == "three-enemy" else MODEL,
                method=METHOD if args.method == "sum-convolution" else PHYSICAL_METHOD,
                max_contributions=args.max_contributions,
                max_payoff_evaluations=args.max_payoff_evaluations,
            )
            rendered = output_bytes(report)
            exit_status = 0 if report["status"] == "complete" else 1
            if report["status"] == "refused":
                failure = report["failure"]
                exit_status = 130 if failure["kind"] == "interrupted" else 1
                print("episode reference: " + failure["message"], file=sys.stderr)
        written = sys.stdout.buffer.write(rendered)
        if written != len(rendered):
            raise RuntimeError("output sink accepted an incomplete document")
        sys.stdout.buffer.flush()
        return exit_status
    except EpisodeInputError as exc:
        parser.error(str(exc))
    except (
        RuntimeError,
        OSError,
        ValueError,
        TypeError,
        ArithmeticError,
        RecursionError,
        MemoryError,
    ) as exc:
        print(f"episode reference: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("episode reference: interrupted before report delivery", file=sys.stderr)
        return 130
    return 2


if __name__ == "__main__":
    exit_status = main()
    if exit_status in (1, 130):
        try:
            sys.stdout.close()
        except OSError:
            pass
    raise SystemExit(exit_status)
