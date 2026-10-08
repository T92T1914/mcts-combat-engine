"""Turn a saved episode into a passive, self-contained HTML reading artifact."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from game.episode_inspection import InspectionRuntimeError, inspection_html
from game.episode_record import EpisodeInputError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect stored episode data without replay or search. Emits HTML.")
    parser.add_argument("record", type=Path, help="saved episode JSON")
    parser.add_argument("--appearance", choices=("obscur", "clair"), default="obscur",
                        help="fixed output appearance (default: obscur)")
    args = parser.parse_args(argv)
    try:
        rendered = inspection_html(args.record, appearance=args.appearance)
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
