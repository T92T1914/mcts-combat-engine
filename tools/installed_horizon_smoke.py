"""Check two retained cells through a relocated companion and installed engine.

This delivery witness checks two retained cells and a separate public API recipe.
It computes one reference, four searches and a zero-work control, not a new study.
The existing installed-consumer job supplies its external root and outer bound.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import sysconfig
from pathlib import Path

import engine

RECIPE_CHECK = '''\
import contextlib
import dataclasses
import importlib.util
import io
import json
import random
import runpy
import sys
import sysconfig
from pathlib import Path

import engine
import engine.mcts as model

origin = Path(engine.__file__).resolve()
assert origin.is_relative_to(Path(sysconfig.get_path("purelib")).resolve())
assert importlib.util.find_spec("game") is None
assert importlib.util.find_spec("reference") is None
calls = 0
original = model.advance_round

def counted(*args, **kwargs):
    global calls
    calls += 1
    return original(*args, **kwargs)

model.advance_round = counted
runs = []
for _ in range(2):
    start = calls
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        namespace = runpy.run_path(sys.argv[1])
    state = namespace["state"]
    before = namespace["before"]
    search = namespace["search"]
    ranked = namespace["ranked"]
    assert state == before
    assert len(ranked) > 0
    assert ranked[0].action in engine.legal_actions(state)
    result = json.loads(stream.getvalue())
    assert result["selected_action"] == dataclasses.asdict(ranked[0].action)
    assert result["mean_shaped_reward"] == ranked[0].win_rate
    assert result["visits"] == ranked[0].visits
    assert calls - start == result["transitions"] == search.last_transitions
    assert 0 < result["transitions"] <= 32
    assert result["simulations"] == 16
    runs.append({
        "result": result, "counted_transitions": calls - start,
        "root": dataclasses.asdict(before),
        "root_after": dataclasses.asdict(state),
        "statistics": [
            [dataclasses.asdict(action), visits, value]
            for action, visits, value in search.last_root_statistics
        ],
    })
assert runs[0] == runs[1]
start = calls
zero = engine.MCTS(horizon_rounds=2, max_sims=0, max_transitions=32,
                   rng=random.Random(19))
assert zero.search(state, time_budget_ms=None) == []
assert calls == start and zero.last_sims == zero.last_transitions == 0
assert state == before
Path(sys.argv[2]).write_text(json.dumps({
    "engine_origin": str(origin), "runs": runs,
    "zero_work_no_recommendation": True,
}, sort_keys=True) + "\\n", encoding="utf-8")
'''


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def recipe_delivery(companion, output):
    """Run the literal trusted guide example with only the installed engine."""
    guide = (companion / "docs/episode-adaptive-reference.md").read_text("utf-8")
    start = "<!-- adaptive-api-recipe:start -->\n```python\n"
    end = "```\n<!-- adaptive-api-recipe:end -->"
    require(guide.count(start) == guide.count(end) == 1, "recipe markers differ")
    recipe = guide.split(start)[1].split(end)[0]
    script = output / "adaptive_search.py"
    script.write_text(recipe, encoding="utf-8")
    receipt_path = output / "api-recipe.json"
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", RECIPE_CHECK,
         str(script), str(receipt_path)],
        cwd=output, stdin=subprocess.DEVNULL, capture_output=True, timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    require(completed.returncode == 0, "installed recipe failed: "
            + completed.stderr.decode("utf-8", errors="replace")[:2000])
    receipt = json.loads(receipt_path.read_bytes())
    expected = json.loads((companion / "examples/adaptive-state.json").read_bytes())

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    for run in receipt["runs"]:
        require(canonical(run["root"]) == canonical(expected),
                "recipe constructs a different modeled root or numeric type")
        require(canonical(run["root_after"]) == canonical(expected),
                "recipe changed its modeled root")
    return {
        "receipt": receipt_path.name,
        "recipe_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "counted_transitions": [run["counted_transitions"]
                                for run in receipt["runs"]],
        "matching_supplied_root": True,
        "repeat_matches": True,
        "zero_work_no_recommendation": receipt["zero_work_no_recommendation"],
    }


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
    api_recipe = recipe_delivery(companion, output)
    require(
        all(path.read_bytes() == body for path, body in before.items()),
        "companion input was modified",
    )
    receipt = {
        "scope": ("One E1 reference and its first two cells (128 search transitions); "
                  "separate public API recipe acceptance; delivery only"),
        "source_commit": manifest["source_commit"],
        "engine_origin": str(origin),
        "implementation": study.consumer.reference_identity(),
        "collector_sha256": study.digest(Path(study.__file__).read_bytes()),
        "reference_sha256": study.digest(study.encoded(reference)),
        "cells": cells,
        "search_transitions": 128,
        "api_recipe": api_recipe,
        "original_payloads_unchanged": True,
    }
    (output / "reference.json").write_bytes(study.encoded(reference))
    (output / "acceptance.json").write_bytes(study.encoded(receipt))
    print(
        "Installed horizon delivery: one reference, two matching cells, "
        "128 study transitions; public API recipe checked separately"
    )


if __name__ == "__main__":
    main()
