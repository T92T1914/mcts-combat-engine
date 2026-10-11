"""Compute an explicit finite reference or passively inspect a saved report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from game.episode_record import EpisodeInputError, output_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Price a saved decision with an explicit bounded reference, "
        "evaluate a supplied adaptive state, or inspect saved reference data."
    )
    parser.add_argument(
        "report",
        type=Path,
        help="saved decision JSON, normalized state with --state-input, "
        "or reference JSON with --inspect",
    )
    parser.add_argument(
        "--state-input",
        action="store_true",
        help="read a complete supplied normalized state "
        "with the explicit two-round adaptive model and method",
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
        choices=("one-round", "three-enemy", "two-round-adaptive"),
        help="calculation subset: one-round retains one/two initial enemies "
        "(default); three-enemy requires exactly three; two-round-adaptive "
        "requires one enemy and at most three plain damage/heal cards",
    )
    parser.add_argument(
        "--method",
        choices=("physical", "sum-convolution", "adaptive-physical"),
        help="calculation method: physical enumeration (default), or explicit "
        "integer sum convolution for the narrower nonlethal damage subset, "
        "or adaptive-physical for the explicit two-round model",
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
        "--max-transitions",
        type=int,
        help="adaptive executed first/second transition leaves, "
        "1..1000000 (default: 1000000)",
    )
    parser.add_argument(
        "--max-per-action",
        type=int,
        help="adaptive transition leaves per root action including continuations, "
        "1..250000 (default: 250000)",
    )
    parser.add_argument(
        "--max-work-units",
        type=int,
        help="adaptive transitions plus payoff and observation operations, "
        "1..3000000 (default: 3000000)",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        help="cooperative deadline, 0.000001..30 for physical enumeration or "
        "finite positive at most 30 for sum-convolution and adaptive-physical "
        "(default: 30, no hard wall or memory guarantee)",
    )
    args = parser.parse_args(argv)
    if args.inspect:
        if (
            any(
                value is not None
                for value in (
                    args.model,
                    args.method,
                    args.max_paths,
                    args.max_total_paths,
                    args.max_contributions,
                    args.max_payoff_evaluations,
                    args.max_transitions,
                    args.max_per_action,
                    args.max_work_units,
                    args.max_seconds,
                )
            )
            or args.state_input
        ):
            parser.error("inspection cannot accept model or calculation controls")
    elif args.compare_report is not None or args.appearance is not None:
        parser.error("--compare-report and --appearance require --inspect")
    elif (
        args.model == "two-round-adaptive"
        or args.method == "adaptive-physical"
        or args.state_input
    ):
        if args.model != "two-round-adaptive" or args.method != "adaptive-physical":
            parser.error(
                "adaptive calculation requires --model two-round-adaptive "
                "and --method adaptive-physical"
            )
        if any(
            value is not None
            for value in (
                args.max_paths,
                args.max_total_paths,
                args.max_contributions,
                args.max_payoff_evaluations,
            )
        ):
            parser.error(
                "adaptive calculation requires its own transition and work controls"
            )
    elif any(
        value is not None
        for value in (args.max_transitions, args.max_per_action, args.max_work_units)
    ):
        parser.error(
            "adaptive transition and work controls require "
            "the two-round adaptive model and method"
        )
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
            from reference.consumer import (
                ADAPTIVE_METHOD,
                ADAPTIVE_MODEL,
                reference_decision,
            )
            from reference.report import MODEL, THREE_ENEMY_MODEL

            report = reference_decision(
                args.report,
                max_paths=250_000 if args.max_paths is None else args.max_paths,
                max_total_paths=(
                    1_000_000 if args.max_total_paths is None else args.max_total_paths
                ),
                max_seconds=30.0 if args.max_seconds is None else args.max_seconds,
                model=ADAPTIVE_MODEL
                if args.model == "two-round-adaptive"
                else THREE_ENEMY_MODEL
                if args.model == "three-enemy"
                else MODEL,
                method=ADAPTIVE_METHOD
                if args.method == "adaptive-physical"
                else METHOD
                if args.method == "sum-convolution"
                else PHYSICAL_METHOD,
                max_contributions=args.max_contributions,
                max_payoff_evaluations=args.max_payoff_evaluations,
                max_transitions=args.max_transitions,
                max_per_action=args.max_per_action,
                max_work_units=args.max_work_units,
                state_input=args.state_input,
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
