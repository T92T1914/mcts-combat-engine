"""Check two retained cells through a relocated companion and installed engine.

This delivery witness computes one reference and two searches, not a new study.
The existing installed-consumer job supplies its external root and outer bound.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import sysconfig
from pathlib import Path

import engine


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    root = Path(sys.argv[1]).resolve()
    companion = root / "relocated-companion"
    origin = Path(engine.__file__).resolve()
    require(
        origin.is_relative_to(Path(sysconfig.get_path("purelib")).resolve()),
        "engine must come from the external installation",
    )
    require(importlib.util.find_spec("game") is None, "wheel contains examples")
    require(importlib.util.find_spec("reference") is None, "wheel contains reference")
    manifest = json.loads((companion / "manifest.json").read_bytes())
    before = {}
    for name, identity in manifest["payload_files"].items():
        path = companion.joinpath(*name.split("/"))
        body = path.read_bytes()
        require(
            identity
            == {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()},
            "companion payload differs: " + name,
        )
        before[path] = body
    for name, identity in manifest["reference_engine"]["files"].items():
        body = origin.parent.joinpath(*name.split("/")[1:]).read_bytes()
        require(
            identity
            == {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()},
            "installed engine differs: " + name,
        )
    sys.path.insert(0, str(companion))
    from tools import two_round_horizon_study as study

    for name, pin in study.PINS.items():
        require(
            study.digest((study.DATA / name).read_bytes()) == pin,
            "frozen input differs: " + name,
        )
    inputs = json.loads((study.DATA / "inputs.json").read_bytes())
    seeds = json.loads((study.DATA / "seeds.json").read_bytes())
    retained = json.loads((study.DATA / "exploratory.json").read_bytes())
    output = root / "horizon-delivery"
    output.mkdir(exist_ok=False)
    state = inputs["cases"]["E1"]
    state_path = output / "E1.state.json"
    state_path.write_bytes(study.encoded(state))
    reference = study.consumer.reference_decision(
        state_path,
        state_input=True,
        model=study.adaptive_report.MODEL,
        method=study.adaptive_report.METHOD,
        max_transitions=10000,
        max_per_action=2500,
        max_work_units=25000,
        max_seconds=10,
    )
    values = study.price_actions(reference, state)
    root_values = next(
        item for item in retained["summary"]["states"] if item["case"] == "E1"
    )["root_values"]
    require(
        values
        == {
            study.action_key(row["action"]): study.fraction(row["value"])
            for row in root_values
        },
        "reference action values differ",
    )
    cells = []
    for horizon in (1, 2):
        cell = study.collect_one(
            study.construct_state(state),
            seeds["exploratory"][0]["E1"][str(horizon)],
            horizon,
            values,
        )
        expected = next(
            row for row in retained["cells"] if row[:3] == [0, "E1", horizon]
        )
        require(
            [
                cell["selected_action"]["card_idx"],
                cell["selected_action"]["target_idx"],
                cell["loss"]["numerator"],
                cell["loss"]["denominator"],
            ]
            == expected[3:],
            "retained action/loss differs",
        )
        cells.append(cell)
    require(
        all(path.read_bytes() == body for path, body in before.items()),
        "companion input was modified",
    )
    receipt = {
        "scope": "One E1 reference and its first two cells; delivery only",
        "source_commit": manifest["source_commit"],
        "engine_origin": str(origin),
        "implementation": study.consumer.reference_identity(),
        "collector_sha256": study.digest(Path(study.__file__).read_bytes()),
        "reference_sha256": study.digest(study.encoded(reference)),
        "cells": cells,
        "search_transitions": 128,
        "original_payloads_unchanged": True,
    }
    (output / "reference.json").write_bytes(study.encoded(reference))
    (output / "acceptance.json").write_bytes(study.encoded(receipt))
    print(
        "Installed horizon delivery: one reference, two matching cells, 128 transitions"
    )


if __name__ == "__main__":
    main()
