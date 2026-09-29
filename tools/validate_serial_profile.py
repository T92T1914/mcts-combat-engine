"""Check retained serial profile receipts without executing search."""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.actions import Action, legal_actions  # noqa: E402
from game.content import SCENARIOS  # noqa: E402
from tools.run_parallel_scaling import digest  # noqa: E402
from tools.run_serial_profile import PROTOCOL, object_digest  # noqa: E402

DATA = ROOT / "docs/serial-profile-results.json"
RESULT_SHA256 = "a528960d7c14724dbb4d90b23133310b15e52bee7ffcf9a1bf2ec910bbb5df63"
EVALUATED_REVISION = "a8e18580401601846fbd21ab27d4731d19cceef6"


def validate(record):
    if (record["status"] != "complete"
            or record["source"]["revision"] != EVALUATED_REVISION
            or not record["source_unchanged_at_end"]
            or record["protocol_sha256"] != digest(PROTOCOL)):
        raise ValueError("Incomplete or changed source identity")
    cells = record["cells"]
    order = [(s, m) for s in ("duel", "gauntlet", "boss")
             for m in ("control", "profiled")]
    if [(c["scenario"], c["mode"]) for c in cells] != order:
        raise ValueError("Missing, repeated or reordered conditions")
    comparisons = []
    for control, profiled in zip(cells[::2], cells[1::2], strict=True):
        if (control["computation"] != profiled["computation"]
                or control["root_sha256"] != profiled["root_sha256"]):
            raise ValueError("Instrumented computation differs from control")
        comparisons.append({"scenario": control["scenario"], "matched": True})
        root, _ = SCENARIOS[control["scenario"]](random.Random(300))
        root.player.pips = 7
        legal = legal_actions(root)
        for cell in (control, profiled):
            computation = cell["computation"]
            if (cell["status"] != "completed" or cell["error"] is not None
                    or not cell["root_unchanged"]
                    or cell["root_sha256"] != object_digest(root)
                    or computation["simulations"] != 3000
                    or computation["transitions"] != 15000
                    or computation["unused_transitions"] != 0
                    or cell["observed_simulations"] != 3000
                    or cell["observed_transitions"] != 15000
                    or set(computation["stop_reasons"])
                    != {"simulation_cap", "transition_allowance"}
                    or not math.isfinite(cell["elapsed_s"])
                    or cell["elapsed_s"] <= 0):
                raise ValueError("Invalid completed work receipt")
            reconstructed = []
            actions = []
            for row in computation["root_statistics"]:
                action = Action(**row["action"])
                if (action not in legal or action in actions
                        or type(row["visits"]) is not int or row["visits"] <= 0
                        or not math.isfinite(row["value_sum"])
                        or not 0 <= row["value_sum"] <= row["visits"]):
                    raise ValueError("Invalid root action statistics")
                actions.append(action)
                reconstructed.append({"action": row["action"],
                                      "label": action.describe(root),
                                      "win_rate": row["value_sum"] / row["visits"],
                                      "visits": row["visits"]})
            reconstructed.sort(key=lambda r: (r["win_rate"], r["visits"]),
                               reverse=True)
            if (sum(r["visits"] for r in reconstructed) != 3000
                    or reconstructed != computation["ranked"]):
                raise ValueError("Rankings do not reconcile with raw statistics")
            if bool(cell["profile"]) != (cell["mode"] == "profiled"):
                raise ValueError("Missing or misplaced profiler output")
            for row in cell["profile"]:
                if ("\\" in row["file"] or ":/" in row["file"]
                        or row["file"].startswith("/")
                        or row["calls"] < row["primitive_calls"]
                        or row["primitive_calls"] < 0
                        or any(not math.isfinite(row[k]) or row[k] < 0
                               for k in ("self_s", "cumulative_s"))):
                    raise ValueError("Invalid or unsanitized profiler row")
    if comparisons != record["comparisons"]:
        raise ValueError("Saved comparisons do not match the receipts")


def main():
    if hashlib.sha256(DATA.read_bytes()).hexdigest() != RESULT_SHA256:
        raise ValueError("The retained first attempt bytes changed")
    record = json.loads(DATA.read_text(encoding="utf-8"))
    validate(record)
    print(json.dumps({"status": "passed", "executions": len(record["cells"]),
                      "evaluated_revision": EVALUATED_REVISION,
                      "retained_sha256": RESULT_SHA256}))


if __name__ == "__main__":
    main()
