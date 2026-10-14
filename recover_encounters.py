"""Inspect a retained encounter capture without executing or replacing trials."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Resolve only this explicitly selected companion under isolated Python.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from game.episode_record import EpisodeInputError
from tools.encounter_recovery import READ_BYTES, RecoveryRuntimeError, recover_capture


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect a stopped inner capture directory. Does not retry work.")
    parser.add_argument("capture", type=Path,
                        help="directory containing protocol.json and trials")
    parser.add_argument("--output", type=Path, required=True,
                        help="new JSON report outside the original capture")
    parser.add_argument("--max-read-bytes", type=int, default=READ_BYTES,
                        help="total retained bytes to inspect, at most 134217728")
    arguments = parser.parse_args(argv)
    try:
        report = recover_capture(arguments.capture, arguments.output,
                                 max_read_bytes=arguments.max_read_bytes)
    except EpisodeInputError as error:
        parser.error(str(error))
    except (RecoveryRuntimeError, OSError, ValueError) as error:
        print("Encounter recovery refused: " + str(error), file=sys.stderr)
        return 1
    counts = report["summary"]["classifications"]
    print("Encounter recovery inspected " + str(report["summary"]["intended_trials"]) +
          " intended slots: " + str(counts["complete_admitted"]) +
          " complete admitted, " + str(counts["incomplete_attempt"]) +
          " incomplete attempts, " + str(counts["corrupt_or_contradictory"]) +
          " corrupt or contradictory, " + str(counts["no_execution_evidence"]) +
          " with no retained execution evidence. See the report for limits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
