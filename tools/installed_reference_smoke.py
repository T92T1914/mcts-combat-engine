"""Exercise the new reference through a relocated, separately acquired companion."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import engine


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    companion = root / "relocated-companion"
    prior = json.loads((root / "acceptance.json").read_bytes())
    origin = Path(engine.__file__).resolve()
    require(
        origin.is_relative_to(Path(sysconfig.get_path("purelib")).resolve()),
        "engine must be installed outside the checkout",
    )
    require(
        importlib.util.find_spec("reference") is None,
        "engine wheel must not install the reference companion",
    )
    outputs = root / "reference-results"
    outputs.mkdir(exist_ok=False)
    working = root / "unrelated-working-directory"
    receipts = []
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in {"PYTHONPATH", "PYTHONHOME"}
    }
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    def encoded(value: dict) -> bytes:
        return (
            json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
        ).encode()

    def write(name: str, data: bytes) -> Path:
        path = outputs / name
        with path.open("xb") as stream:
            require(stream.write(data) == len(data), "short acceptance output")
        return path

    def call(
        entry: str,
        arguments: list[str],
        name: str,
        status: int = 0,
        *,
        passive: bool = False,
    ) -> bytes:
        # This child imports installed classes and complete companion helpers.
        # Guards deny numerical work in passive modes and all search in compute.
        guarded = (
            "import sys,runpy;sys.path.insert(0,sys.argv.pop(1));"
            "import engine,engine.mcts,engine.simulator;"
            "import game.episode_record as records;"
            "import reference.one_round as core;"
            "\n"
            "def deny(*args,**kwargs):\n"
            ' raise RuntimeError("forbidden consumer work reached")\n'
            "engine.MCTS.__init__=deny;engine.MCTS.search=deny;"
            "engine.mcts.advance_round=deny;engine.simulator.advance_round=deny;"
            "engine.advance_round=deny;records._record_owner=deny;"
            + (
                "core.evaluate=deny;core.enumerate_action=deny;core.score=deny;"
                if passive
                else ""
            )
            + 'sys.argv=sys.argv[1:];runpy.run_path(sys.argv[0],run_name="__main__")'
        )
        if entry == "reference_episode.py":
            command = [
                sys.executable,
                "-I",
                "-B",
                "-c",
                guarded,
                str(companion),
                str(companion / entry),
                *arguments,
            ]
        else:
            command = [
                sys.executable,
                "-E",
                "-s",
                "-B",
                str(companion / entry),
                *arguments,
            ]
        completed = subprocess.run(
            command,
            cwd=working,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            shell=False,
        )
        require(
            completed.returncode == status,
            name
            + ": status "
            + str(completed.returncode)
            + ": "
            + completed.stderr.decode("utf-8", "replace"),
        )
        require(
            completed.stdout.endswith(b"\n") and b"\r\n" not in completed.stdout,
            name + ": incomplete/LF document",
        )
        require(bool(completed.stderr) == bool(status), name + ": diagnostic mismatch")
        write(name, completed.stdout)
        receipts.append(
            {
                "entry": entry,
                "output": name,
                "status": status,
                "sha256": hashlib.sha256(completed.stdout).hexdigest(),
                "bytes": len(completed.stdout),
                "search_guarded": entry == "reference_episode.py",
                "reference_guarded": passive,
            }
        )
        return completed.stdout

    # Preserve the accepted boss journey, then record a genuinely new supported
    # custom episode. These fixtures are controlled consumer inputs, not demand.
    cards = root / "inputs" / "cards.json"
    original = cards.read_bytes()
    scenarios = write(
        "scenarios.json",
        encoded(
            {
                "scenarios": {
                    "bounded": {
                        "player": {
                            "name": "Operator",
                            "element": "ember",
                            "hp": 10000,
                            "power_pip_chance": 0.4,
                        },
                        "deck": ["Pulse"],
                        "enemies": [
                            {
                                "name": "Target",
                                "element": "frost",
                                "hp": 1000,
                                "power_pip_chance": 0.0,
                                "attack": {
                                    "name": "Reply",
                                    "element": "frost",
                                    "type": "damage",
                                    "accuracy": 0.8,
                                    "damage_min": 1,
                                    "damage_max": 2,
                                },
                            }
                        ],
                    }
                }
            }
        ),
    )
    content = ["--cards", str(cards), "--scenarios", str(scenarios)]
    record = outputs / "episode.json"
    call(
        "episode.py",
        [
            "record",
            "bounded",
            *content,
            "--rounds",
            "2",
            "--sims",
            "2",
            "--horizon",
            "1",
        ],
        record.name,
    )
    call("episode.py", ["replay", str(record), *content], "replay.json")
    for label, seed in (("a", "19"), ("b", "23")):
        decision_path = outputs / ("decision-" + label + ".json")
        call(
            "decide_episode.py",
            [
                str(record),
                "--step",
                "0",
                "--sims",
                "16",
                "--horizon",
                "1",
                "--seed",
                seed,
                "--final-action-rule",
                "mean_visits",
            ],
            decision_path.name,
        )
        value = json.loads(
            call(
                "reference_episode.py",
                [str(decision_path), "--max-seconds", "10"],
                "reference-" + label + ".json",
            )
        )
        require(value["status"] == "complete", "supported installed reference refused")
        require(
            value["implementation"]["decision_consumer"]["engine_import_kind"]
            == "site-packages",
            "reference did not bind installed engine",
        )
        require(value["evaluation"]["total_leaves"] > 0, "empty full-action report")
    left, right = outputs / "reference-a.json", outputs / "reference-b.json"
    call(
        "decide_episode.py",
        [
            str(record),
            "--step",
            "0",
            "--stability",
            "--seeds",
            "19",
            "23",
            "--explorations",
            "1.2",
            "--horizon",
            "1",
        ],
        "stability.json",
    )
    call(
        "decide_episode.py",
        [
            str(outputs / "stability.json"),
            "--extract-cell",
            "0",
            "--final-action-rule",
            "visits_mean",
        ],
        "extracted.json",
    )
    extracted = json.loads(
        call(
            "reference_episode.py",
            [str(outputs / "extracted.json")],
            "extracted-reference.json",
        )
    )
    require(
        extracted["status"] == "complete"
        and extracted["decision_report"]["derivation"]["new_search_performed"] is False,
        "reference did not consume the passively extracted stability cell",
    )
    call(
        "reference_episode.py", [str(left), "--inspect"], "reference.html", passive=True
    )
    call(
        "reference_episode.py",
        [str(left), "--inspect", "--compare-report", str(right)],
        "comparison.html",
        passive=True,
    )
    refusal = json.loads(
        call(
            "reference_episode.py",
            [str(outputs / "decision-a.json"), "--max-total-paths", "1"],
            "cap-refused.json",
            1,
        )
    )
    require(
        refusal["evaluation"] is None
        and refusal["diagnostics"] is None
        and refusal["failure"]["kind"] == "work_limit",
        "cap leaked partial values",
    )
    call(
        "reference_episode.py",
        [str(outputs / "cap-refused.json"), "--inspect"],
        "cap-refused.html",
        passive=True,
    )
    refusal = json.loads(
        call(
            "reference_episode.py",
            [str(root / "results" / "visits_mean.json")],
            "boss-refused.json",
            1,
        )
    )
    require(
        refusal["failure"]["kind"] == "unsupported_state"
        and refusal["evaluation"] is None,
        "boss mechanics were silently discarded",
    )
    deadline = json.loads(
        call(
            "reference_episode.py",
            [str(outputs / "decision-a.json"), "--max-seconds", "0.000001"],
            "deadline-refused.json",
            1,
        )
    )
    require(
        deadline["failure"]["kind"] == "work_limit" and deadline["evaluation"] is None,
        "deadline retained an unfinished expectation",
    )
    call(
        "decide_episode.py",
        [str(record), "--step", "0", "--sims", "2", "--horizon", "2"],
        "horizon-two.json",
    )
    horizon = json.loads(
        call(
            "reference_episode.py",
            [str(outputs / "horizon-two.json")],
            "horizon-refused.json",
            1,
            passive=True,
        )
    )
    require(
        horizon["failure"]["kind"] == "horizon_mismatch",
        "reference priced a different search horizon",
    )
    # Exercise the explicit additive model using the actual bundled encounter.
    # The seeds and one-round work match its prior qualification protocol.
    three_model = "independent_one_round_three_enemy_binary53_shaped_v1"
    gauntlet = outputs / "gauntlet-episode.json"
    call(
        "episode.py",
        [
            "record",
            "gauntlet",
            "--environment-seed",
            "37",
            "--search-seed",
            "41",
            "--rounds",
            "1",
            "--sims",
            "16",
            "--horizon",
            "1",
        ],
        gauntlet.name,
    )
    call("episode.py", ["replay", str(gauntlet)], "gauntlet-replay.json")
    gauntlet_decision = outputs / "gauntlet-decision.json"
    gauntlet_search = json.loads(
        call(
            "decide_episode.py",
            [
                str(gauntlet),
                "--step",
                "0",
                "--sims",
                "16",
                "--horizon",
                "1",
                "--seed",
                "43",
            ],
            gauntlet_decision.name,
        )
    )
    qualified_state = json.dumps(
        gauntlet_search["selected_state"],
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    require(
        hashlib.sha256(qualified_state).hexdigest()
        == "c96f3185761f5f0ca71d05defd1f1c2c25636b3fd03c64f58b38013ecc712237",
        "newly recorded gauntlet state differs from the independently qualified root",
    )
    old_refusal = json.loads(
        call(
            "reference_episode.py",
            [str(gauntlet_decision)],
            "gauntlet-default-refused.json",
            1,
        )
    )
    require(
        old_refusal["model"] == "independent_one_round_binary53_shaped_v1"
        and old_refusal["failure"]["kind"] == "unsupported_state"
        and old_refusal["evaluation"] is None,
        "omitted selection silently promoted the default model",
    )
    three_references = []
    for label, seconds in (("a", "10"), ("b", "5")):
        path = outputs / ("gauntlet-reference-" + label + ".json")
        value = json.loads(
            call(
                "reference_episode.py",
                [
                    str(gauntlet_decision),
                    "--model",
                    "three-enemy",
                    "--max-seconds",
                    seconds,
                ],
                path.name,
            )
        )
        expected_ties = [{"card_idx": 2, "target_idx": target} for target in range(3)]
        require(
            value["status"] == "complete"
            and value["model"] == three_model
            and value["evaluation"]["model"] == three_model
            and value["evaluation"]["total_leaves"] == 1504
            and value["evaluation"]["best_actions"] == expected_ties
            and value["diagnostics"]["recommendation"]["reference_best"],
            "actual gauntlet report differs from the qualified complete result",
        )
        require(
            value["implementation"]["decision_consumer"]["engine_import_kind"]
            == "site-packages",
            "three-enemy report did not bind installed engine",
        )
        require(
            [row["expected_value"] for row in value["evaluation"]["actions"]]
            == [{"numerator": "1", "denominator": "2"}]
            + [{"numerator": "143673016476077679", "denominator": "279223176896970752"}]
            * 3,
            "genuine gauntlet values differ from the independently qualified fractions",
        )
        require(
            all(
                row["win_mass"]
                == row["loss_mass"]
                == {"numerator": "0", "denominator": "1"}
                and row["ongoing_mass"] == {"numerator": "1", "denominator": "1"}
                for row in value["evaluation"]["actions"]
            ),
            "genuine gauntlet outcome masses changed",
        )
        three_references.append(value)
    require(
        three_references[0]["evaluation"]["actions"]
        == three_references[1]["evaluation"]["actions"],
        "changing only a sufficient time allowance changed exact results",
    )
    three_left = outputs / "gauntlet-reference-a.json"
    call(
        "reference_episode.py",
        [str(three_left), "--inspect"],
        "gauntlet-reference.html",
        passive=True,
    )
    call(
        "reference_episode.py",
        [
            str(three_left),
            "--inspect",
            "--compare-report",
            str(outputs / "gauntlet-reference-b.json"),
        ],
        "gauntlet-comparison.html",
        passive=True,
    )
    mixed = call(
        "reference_episode.py",
        [str(three_left), "--inspect", "--compare-report", str(left)],
        "mixed-model-comparison.html",
        passive=True,
    )
    require(b"model_differs" in mixed, "mixed model comparison lost its boundary")
    three_refusal = json.loads(
        call(
            "reference_episode.py",
            [
                str(gauntlet_decision),
                "--model",
                "three-enemy",
                "--max-total-paths",
                "1",
            ],
            "gauntlet-cap-refused.json",
            1,
        )
    )
    require(
        three_refusal["model"] == three_model
        and three_refusal["failure"]["kind"] == "work_limit"
        and three_refusal["evaluation"] is None
        and three_refusal["diagnostics"] is None,
        "new model cap leaked partial values",
    )
    call(
        "reference_episode.py",
        [str(outputs / "gauntlet-cap-refused.json"), "--inspect"],
        "gauntlet-cap-refused.html",
        passive=True,
    )

    # Record physical duplicates rather than fabricating episode provenance.
    # All three responses cost three pips and are initially unaffordable.
    duplicate_scenario = write(
        "three-target-scenarios.json",
        encoded(
            {
                "scenarios": {
                    "three_targets": {
                        "player": {
                            "name": "Operator",
                            "element": "ember",
                            "hp": 10000,
                            "power_pip_chance": 0.4,
                        },
                        "deck": ["Pulse"],
                        "enemies": [
                            {
                                "name": "Target " + str(target),
                                "element": "frost",
                                "hp": 1000,
                                "power_pip_chance": 0.0,
                                "attack": {
                                    "name": "Reply",
                                    "element": "frost",
                                    "type": "damage",
                                    "pip_cost": 3,
                                    "accuracy": 0.8,
                                    "damage_min": 1,
                                    "damage_max": 2,
                                },
                            }
                            for target in range(3)
                        ],
                    }
                },
            }
        ),
    )
    duplicate_content = ["--cards", str(cards), "--scenarios", str(duplicate_scenario)]
    duplicate_episode = outputs / "three-target-episode.json"
    call(
        "episode.py",
        [
            "record",
            "three_targets",
            *duplicate_content,
            "--rounds",
            "1",
            "--sims",
            "16",
            "--horizon",
            "1",
        ],
        duplicate_episode.name,
    )
    call(
        "episode.py",
        ["replay", str(duplicate_episode), *duplicate_content],
        "three-target-replay.json",
    )
    duplicate_decision = outputs / "three-target-decision.json"
    call(
        "decide_episode.py",
        [str(duplicate_episode), "--step", "0", "--sims", "16", "--horizon", "1"],
        duplicate_decision.name,
    )
    duplicates = json.loads(
        call(
            "reference_episode.py",
            [str(duplicate_decision), "--model", "three-enemy", "--max-seconds", "10"],
            "three-target-reference.json",
        )
    )
    physical = [{"card_idx": None, "target_idx": None}] + [
        {"card_idx": card, "target_idx": target}
        for card in range(7)
        for target in range(3)
    ]
    require(
        duplicates["status"] == "complete"
        and [row["action"] for row in duplicates["evaluation"]["actions"]] == physical
        and len(duplicates["evaluation"]["best_actions"]) == 21,
        "maximum physical action report merged duplicates or omitted a third target",
    )
    call(
        "reference_episode.py",
        [str(outputs / "three-target-reference.json"), "--inspect"],
        "three-target-reference.html",
        passive=True,
    )
    historical = None
    if len(sys.argv) == 3:
        retained = Path(sys.argv[2]).resolve().read_bytes()
        saved = write("historical-reference.json", retained)
        call(
            "reference_episode.py",
            [str(saved), "--inspect"],
            "historical-reference.html",
            passive=True,
        )
        require(
            saved.read_bytes() == retained,
            "historical report changed during inspection",
        )
        historical = {
            "bytes": len(retained),
            "sha256": hashlib.sha256(retained).hexdigest(),
            "actual_prior_report_inspected": True,
        }
    require(cards.read_bytes() == original, "accepted card input changed")
    summary = {
        "installed_engine": str(origin),
        "companion_source": prior["companion_source"],
        "receipts": receipts,
        "root": str(root),
        "recorded_supported_episode": str(record),
        "recorded_three_enemy_episode": str(gauntlet),
        "recorded_twenty_two_action_episode": str(duplicate_episode),
        "explicit_three_enemy_model": three_model,
        "historical_report": historical,
        "accepted_prior_journey_preserved": True,
    }
    write("acceptance.json", encoded(summary))
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
