"""Run one supported encounter block through the delivered Windows owner."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The internal worker is isolated with -I and deliberately imports this companion.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from game.episode_record import EpisodeInputError
from tools.encounter_process import EnforcementUnavailable
from tools.managed_encounter import run_managed, run_worker


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "_worker":
        try:
            return run_worker(Path(sys.argv[2]))
        except (OSError, ValueError, RuntimeError, ArithmeticError) as error:
            print("managed worker: " + str(error)[:2048], file=sys.stderr)
            return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--wall-seconds", type=float, default=60)
    parser.add_argument("--cleanup-seconds", type=float, default=5)
    parser.add_argument("--memory-mib", type=int, default=256)
    parser.add_argument("--artifact-mib", type=int, default=32)
    parser.add_argument("--cancel-file", type=Path)
    args = parser.parse_args()
    try:
        result, status = run_managed(
            args.protocol, args.output, wall_seconds=args.wall_seconds,
            cleanup_seconds=args.cleanup_seconds, memory_mib=args.memory_mib,
            artifact_mib=args.artifact_mib, cancel_path=args.cancel_file)
    except EnforcementUnavailable as error:
        print(json.dumps({"status": "unsupported", "reason": str(error),
                          "work_admitted": False}), file=sys.stderr)
        return 2
    except (EpisodeInputError, OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "refused", "reason": str(error)[:2048]}),
              file=sys.stderr)
        return 1
    print(json.dumps({"status": result["status"], "output": str(args.output),
                      "failure_kind": result["owner"].get("failure_kind")}))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
