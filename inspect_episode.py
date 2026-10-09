"""Turn a saved episode or decision report into passive self-contained HTML."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from game.episode_inspection import (
    InspectionRuntimeError,
    decision_comparison_html,
    decision_inspection_html,
    inspection_html,
)
from game.episode_record import EpisodeInputError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect stored episode or decision data without work. Emits HTML.")
    parser.add_argument("record", type=Path,
                        help="episode JSON, or decision JSON with --decision-report")
    parser.add_argument("--appearance", choices=("obscur", "clair"), default="obscur",
                        help="fixed output appearance (default: obscur)")
    parser.add_argument("--decision-report", action="store_true",
                        help="read mcts-episode-decision-report schema 1 explicitly")
    parser.add_argument("--compare-report", type=Path, metavar="RIGHT",
                        help="compare a second saved report with --decision-report")
    args = parser.parse_args(argv)
    if args.compare_report is not None and not args.decision_report:
        parser.error("--compare-report requires --decision-report")
    try:
        if args.compare_report is not None:
            rendered = decision_comparison_html(args.record, args.compare_report,
                                                appearance=args.appearance)
        else:
            render = (decision_inspection_html if args.decision_report
                      else inspection_html)
            rendered = render(args.record, appearance=args.appearance)
        written = sys.stdout.buffer.write(rendered)
        if written != len(rendered):
            raise InspectionRuntimeError("output sink accepted an incomplete document")
        sys.stdout.buffer.flush()
    except EpisodeInputError as exc:
        parser.error(str(exc))
    except (InspectionRuntimeError, OSError, ValueError, TypeError,
            OverflowError, RecursionError, MemoryError) as exc:
        print(f"episode inspection: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("episode inspection: interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    exit_status = main()
    if exit_status in (1, 130):
        # Retire a failed buffered sink before interpreter shutdown can retry it.
        try:
            sys.stdout.close()
        except OSError:
            pass
    raise SystemExit(exit_status)
