"""Exercise the new reference through a relocated, separately acquired companion."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import sysconfig
from html.parser import HTMLParser
from pathlib import Path

import engine


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


class SavedFragments(HTMLParser):
    """Read visible escaped JSON without importing the report renderer."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pointer = None
        self.parts = []
        self.fragments = {}

    def handle_starttag(self, tag, attributes):
        if tag == "pre" and "data-json-pointer" in dict(attributes):
            require(self.pointer is None, "nested saved JSON fragment")
            self.pointer = dict(attributes)["data-json-pointer"]
            require(self.pointer not in self.fragments, "duplicate saved JSON fragment")
            self.parts = []

    def handle_data(self, data):
        if self.pointer is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "pre" and self.pointer is not None:
            self.fragments[self.pointer] = json.loads("".join(self.parts))
            self.pointer = None
            self.parts = []


def saved_fragments(body: bytes) -> dict:
    parsed = SavedFragments()
    parsed.feed(body.decode("utf-8"))
    parsed.close()
    require(parsed.pointer is None, "incomplete saved JSON fragment")
    return parsed.fragments


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
            "import reference.aggregation as aggregate;"
            "\n"
            "def deny(*args,**kwargs):\n"
            ' raise RuntimeError("forbidden consumer work reached")\n'
            "engine.MCTS.__init__=deny;engine.MCTS.search=deny;"
            "engine.mcts.advance_round=deny;engine.simulator.advance_round=deny;"
            "engine.advance_round=deny;records._record_owner=deny;"
            + (
                "core.evaluate=deny;core.enumerate_action=deny;core.score=deny;"
                "aggregate.evaluate=deny;aggregate._Budget.payoff=deny;"
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
    # These are newly recorded modeled calibration inputs, not captured encounters.
    # The loader creates seven physical copies from the one-card custom deck.
    # Keep the real acquisition/record/replay/decision chain instead of changing
    # its saved state or manufacturing an episode around the one-card probe.
    sum_scenarios = write(
        "sum-modeled-scenarios.json",
        encoded({
            "scenarios": {
                "modeled_area": {
                    "description": "Modeled sum calibration, not a captured encounter",
                    "player": {
                        "name": "Modeled operator", "element": "ember",
                        "hp": 1000, "power_pip_chance": 0,
                    },
                    "deck": ["Modeled area"],
                    "enemies": [
                        {
                            "name": "Modeled target " + str(index),
                            "element": "frost", "hp": 1000,
                            "power_pip_chance": 0,
                        }
                        for index in range(3)
                    ],
                },
            },
        }),
    )
    sum_acceptance = []
    sum_method = "integer_sum_convolution_v1"
    for label, width in (("wide", 151), ("small", 3)):
        sum_cards = write(
            "sum-" + label + "-cards.json",
            encoded({"cards": [{
                "name": "Modeled area", "element": "ember", "type": "damage",
                "pip_cost": 0, "accuracy": 1, "damage_min": 1,
                "damage_max": width, "hits_all": True,
            }]}),
        )
        sum_content = ["--cards", str(sum_cards), "--scenarios", str(sum_scenarios)]
        source_inputs = {
            path: path.read_bytes() for path in (sum_cards, sum_scenarios)
        }
        sum_episode = outputs / ("sum-" + label + "-episode.json")
        call(
            "episode.py",
            [
                "record", "modeled_area", *sum_content,
                "--environment-seed", "31", "--search-seed", "37",
                "--rounds", "1", "--sims", "2", "--horizon", "1",
            ],
            sum_episode.name,
        )
        recorded_episode = sum_episode.read_bytes()
        replay = json.loads(call(
            "episode.py", ["replay", str(sum_episode), *sum_content],
            "sum-" + label + "-replay.json",
        ))
        require(
            replay["status"] == "environment_replay_verified"
            and replay["search_recomputed"] is False,
            "modeled sum episode failed environment replay without search",
        )
        sum_decision = outputs / ("sum-" + label + "-decision.json")
        call(
            "decide_episode.py",
            [
                str(sum_episode), "--step", "0", "--seed", "41",
                "--sims", "16", "--horizon", "1",
            ],
            sum_decision.name,
        )
        protected_inputs = {
            **source_inputs,
            sum_episode: recorded_episode,
            sum_decision: sum_decision.read_bytes(),
        }
        sum_report_path = outputs / ("sum-" + label + "-reference.json")
        raw_sum_report = call(
            "reference_episode.py",
            [
                str(sum_decision), "--model", "three-enemy",
                "--method", "sum-convolution", "--max-seconds", "10",
            ],
            sum_report_path.name,
        )
        sum_report = json.loads(raw_sum_report)
        evaluation = sum_report["evaluation"]
        expected_actions = [{"card_idx": None, "target_idx": None}] + [
            {"card_idx": index, "target_idx": None} for index in range(7)
        ]
        require(
            sum_report["status"] == "complete"
            and sum_report["schema_version"] == 2
            and sum_report["computation_method"] == sum_method
            and sum_report["model"] == three_model
            and sum_report["new_search_performed"] is False
            and [row["action"] for row in evaluation["actions"]] == expected_actions
            and evaluation["best_actions"] == expected_actions[1:]
            and "total_leaves" not in evaluation
            and all("leaves" not in row for row in evaluation["actions"]),
            "installed sum consumer changed method, physical actions or work meaning",
        )
        require(
            sum_report["implementation"]["decision_consumer"]["engine_import_kind"]
            == "site-packages",
            "sum report did not identify the installed engine",
        )
        require(
            all(
                row["mass"] == row["ongoing_mass"]
                == {"numerator": "1", "denominator": "1"}
                and row["win_mass"] == row["loss_mass"]
                == {"numerator": "0", "denominator": "1"}
                for row in evaluation["actions"]
            ),
            "sum consumer changed the qualified all-ongoing masses",
        )
        if width == 151:
            expected_value = {
                "numerator": "8342051988272323598463",
                "denominator": "15505672840654876573696",
            }
            expected_work = {
                "contributions": 68_403, "payoff_evaluations": 451,
                "peak_bins": 451, "represented_damage_combinations": 3_442_951,
                "represented_trace_leaves": 3_442_951,
            }
            require(
                evaluation["actions"][0]["expected_value"]
                == {"numerator": "1", "denominator": "2"}
                and all(
                    row["expected_value"] == expected_value
                    and row["work"] == expected_work
                    for row in evaluation["actions"][1:]
                )
                and evaluation["work"] == {
                    "contributions": 478_821, "payoff_evaluations": 3158,
                    "peak_bins": 451,
                    "represented_damage_combinations": 24_100_658,
                    "represented_trace_leaves": 24_100_658,
                },
                "installed wide values or counters differ from qualification",
            )
            physical_refusal = json.loads(call(
                "reference_episode.py",
                [str(sum_decision), "--model", "three-enemy", "--max-paths", "1"],
                "sum-wide-physical-refused.json", 1,
            ))
            require(
                physical_refusal["schema_version"] == 1
                and "computation_method" not in physical_refusal
                and physical_refusal["failure"]["kind"] == "work_limit"
                and physical_refusal["evaluation"] is None
                and physical_refusal["diagnostics"] is None,
                "default physical cap did not retain its complete-result refusal",
            )
            sum_refusal = json.loads(call(
                "reference_episode.py",
                [
                    str(sum_decision), "--model", "three-enemy",
                    "--method", "sum-convolution", "--max-contributions", "1",
                ],
                "sum-wide-work-refused.json", 1,
            ))
            require(
                sum_refusal["schema_version"] == 2
                and sum_refusal["computation_method"] == sum_method
                and sum_refusal["failure"]["kind"] == "work_limit"
                and sum_refusal["evaluation"] is None
                and sum_refusal["diagnostics"] is None,
                "sum contribution cap retained partial values",
            )
        else:
            physical_path = outputs / "sum-small-physical.json"
            raw_physical = call(
                "reference_episode.py",
                [str(sum_decision), "--model", "three-enemy", "--max-seconds", "10"],
                physical_path.name,
            )
            physical_report = json.loads(raw_physical)
            physical_evaluation = physical_report["evaluation"]
            require(
                physical_report["schema_version"] == 1
                and "computation_method" not in physical_report
                and physical_evaluation["total_leaves"] == 190
                and physical_evaluation["best_actions"] == evaluation["best_actions"]
                and physical_report["diagnostics"] == sum_report["diagnostics"]
                and [
                    {key: value for key, value in row.items() if key != "leaves"}
                    for row in physical_evaluation["actions"]
                ] == [
                    {key: value for key, value in row.items() if key != "work"}
                    for row in evaluation["actions"]
                ],
                "installed methods disagree on small complete values, ties or losses",
            )
            compared = call(
                "reference_episode.py",
                [
                    str(physical_path), "--inspect", "--compare-report",
                    str(sum_report_path),
                ],
                "sum-method-comparison.html", passive=True,
            )
            compared_fragments = saved_fragments(compared)
            require(
                compared_fragments["/left/evaluation"] == physical_evaluation
                and compared_fragments["/right/evaluation"] == evaluation
                and compared_fragments["/left/diagnostics"]
                == physical_report["diagnostics"]
                and compared_fragments["/right/diagnostics"]
                == sum_report["diagnostics"]
                and b"equal exact one-round value loss" in compared
                and b"reported_reference_values_disagree" not in compared
                and physical_path.read_bytes() == raw_physical,
                "passive cross-method comparison changed or misread saved results",
            )
        inspected = call(
            "reference_episode.py", [str(sum_report_path), "--inspect"],
            "sum-" + label + "-reference.html", passive=True,
        )
        inspected_fragments = saved_fragments(inspected)
        require(
            inspected_fragments["/evaluation"] == evaluation
            and inspected_fragments["/diagnostics"] == sum_report["diagnostics"]
            and inspected_fragments["/decision_report/selected_state"]
            == sum_report["decision_report"]["selected_state"]
            and b"Executed integer contribution updates" in inspected
            and b"Represented positive physical trace leaves" in inspected
            and b"not enumerated" in inspected
            and b"<script" not in inspected
            and sum_report_path.read_bytes() == raw_sum_report,
            "passive sum inspection changed saved fragments or work meaning",
        )
        require(
            all(path.read_bytes() == body for path, body in protected_inputs.items()),
            "sum calculation or passive reading changed an admitted input",
        )
        sum_acceptance.append({
            "kind": "newly recorded modeled calibration, not a captured encounter",
            "damage_width": width, "physical_actions": len(expected_actions),
            "method": sum_method, "work": evaluation["work"],
            "report_sha256": hashlib.sha256(raw_sum_report).hexdigest(),
            "input_bytes_preserved": True,
            "passive_saved_fragments_checked": True,
            "cross_method_complete_parity_checked": width == 3,
        })

    historical = None
    if len(sys.argv) == 3:
        retained = Path(sys.argv[2]).resolve().read_bytes()
        saved = write("historical-reference.json", retained)
        historical_html = call(
            "reference_episode.py",
            [str(saved), "--inspect"],
            "historical-reference.html",
            passive=True,
        )
        historical_value = json.loads(retained)
        if historical_value["status"] == "complete":
            fragments = saved_fragments(historical_html)
            require(
                fragments["/evaluation"] == historical_value["evaluation"]
                and fragments["/diagnostics"] == historical_value["diagnostics"],
                "historical reader changed raw saved values or diagnostics",
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
        "aggregation_acceptance": sum_acceptance,
        "accepted_prior_journey_preserved": True,
    }
    write("acceptance.json", encoded(summary))
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
