"""Exercise the new reference through a relocated, separately acquired companion."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import sysconfig
from fractions import Fraction
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
    require(
        importlib.util.find_spec("game") is None,
        "engine wheel must not install the example helpers",
    )
    installed_files = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(origin.parent.glob("*.py"))
    }
    installed_files["py.typed"] = hashlib.sha256(
        (origin.parent / "py.typed").read_bytes()).hexdigest()
    require(set(installed_files) == {
        "__init__.py", "actions.py", "decider.py", "mcts.py", "parallel.py",
        "py.typed", "rules.py", "simulator.py", "state.py",
    }, "installed engine source map must remain complete and engine-only")
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

    def encoded(value: object) -> bytes:
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
            "import engine,engine.mcts,engine.simulator,engine.parallel;"
            "import game.episode_record as records;"
            "import reference.one_round as core;"
            "import reference.aggregation as aggregate;"
            "import reference.adaptive as adaptive;"
            "\n"
            "def deny(*args,**kwargs):\n"
            ' raise RuntimeError("forbidden consumer work reached")\n'
            "engine.MCTS.__init__=deny;engine.MCTS.search=deny;"
            "engine.parallel.ParallelMCTS.__init__=deny;"
            "engine.parallel.ParallelMCTS.search=deny;"
            "engine.mcts.advance_round=deny;engine.simulator.advance_round=deny;"
            "engine.advance_round=deny;records._record_owner=deny;"
            + (
                "core.evaluate=deny;core.enumerate_action=deny;core.score=deny;"
                "aggregate.evaluate=deny;aggregate._Budget.payoff=deny;"
                "adaptive.evaluate=deny;"
                if passive
                else ""
            )
            + 'sys.argv=sys.argv[1:];runpy.run_path(sys.argv[0],run_name="__main__")'
        )
        guard_search = entry == "reference_episode.py" or passive
        if guard_search:
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
        if entry == "decide_episode.py" and status == 2:
            require(completed.stdout == b"",
                    name + ": refused controls emitted a report")
        else:
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
                "search_guarded": guard_search,
                "simulator_guarded": guard_search,
                "record_guarded": guard_search,
                "reference_guarded": guard_search and passive,
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

    # Reuse the genuinely recorded custom episode for the optional treatment.
    # Saved HTML fragments are checked against input JSON, never renderer output.
    record_bytes = record.read_bytes()
    saved_record = json.loads(record_bytes)
    allocation_arguments = [str(record), "--step", "0", "--horizon", "1",
                            "--seed", "19"]
    allocation_reports = {}
    retained_allocation_inputs = {record: record_bytes}
    for label, sims, mode in (("halving", 32, "halving"),
                              ("tiny", 2, "uniform_fallback"),
                              ("zero", 0, "uniform_fallback")):
        path = outputs / ("root-allocation-" + label + ".json")
        body = call(
            "decide_episode.py",
            [*allocation_arguments, "--sims", str(sims),
             "--root-allocation", "sequential_halving"], path.name,
            passive=sims == 0,
        )
        report = json.loads(body)
        allocation = report["root_allocation"]
        require(
            report["schema_version"] == 3
            and report["status"] == ("decision" if sims else "no_work")
            and report["search_performed"] is bool(sims)
            and encoded(report["selected_state"])
            == encoded(saved_record["steps"][0]["state"])
            and report["source_record"] == {
                "bytes": len(record_bytes),
                "sha256": hashlib.sha256(record_bytes).hexdigest()}
            and report["configuration"]["root_allocation"] == "sequential_halving"
            and report["configuration"]["sampling_policy"]
            == "budget_aware_sequential_halving_v1"
            and report["configuration"]["final_action_rule"] == "survivor_mean_visits"
            and report["configuration"]["tie_break"] == "physical_canonical_order"
            and report["configuration"]["max_sims"]
            == report["configuration"]["max_transitions"] == sims
            and report["configuration"]["time_budget_ms"] is None
            and report["configuration"]["priors"] is None
            and report["configuration"]["parallel"] is False
            and allocation["mode"] == mode and allocation["complete"] is True
            and allocation["usable_allowance"] == allocation["selections"]
            == allocation["reward_updates"] == report["work"]["simulations"]
            == report["work"]["transitions"] == sims
            and report["work"]["unused_transitions"] == 0
            and report["implementation"]["engine_import_kind"] == "site-packages"
            and report["implementation"]["engine_files_sha256"] == installed_files,
            "optional allocation lost its treatment, input, work or installed source",
        )
        if sims:
            require(
                report["recommendation"] is not None
                and {key: report["recommendation"][key]
                     for key in ("card_idx", "target_idx")}
                == allocation["winner"]
                and sum(row["visits"] for row in report["legal_actions"]) == sims,
                "optional allocation lost the actual sampled recommendation or visits",
            )
            require(report["work"]["stop_reasons"]
                    == ["transition_allowance", "simulation_cap"],
                    "optional allocation changed its completed-work stopping reasons")
        else:
            require(
                report["ranking"] == [] and report["recommendation"] is None
                and allocation["winner"] is None and allocation["phases"] == []
                and report["work"]["stop_reasons"] == ["zero_requested_simulations"]
                and all(row["status"] == "unvisited" and row["visits"] == 0
                        and row["mean_shaped_reward"] is None
                        for row in report["legal_actions"]),
                "guarded zero work invented a sampled value or winner",
            )
        if mode == "uniform_fallback":
            require(allocation["phases"] == []
                    and allocation["elimination_rounds"] == 0
                    and allocation["elimination_key_evaluations"] == 0,
                    "tiny or zero allowance invented an elimination phase")
        if label == "tiny":
            require(sum(row["visits"] > 0 for row in report["legal_actions"]) == 2
                    and any(row["mean_shaped_reward"] is None
                            for row in report["legal_actions"]),
                    "tiny allowance fabricated values for unvisited physical actions")
        html = call(
            "inspect_episode.py", [str(path), "--decision-report"],
            "root-allocation-" + label + ".html", passive=True,
        )
        fragments = saved_fragments(html)
        for branch in ("selected_state", "legal_actions", "ranking", "recommendation",
                       "configuration", "work", "root_allocation", "implementation",
                       "stored_provenance", "identity_comparisons"):
            require(encoded(fragments["/" + branch]) == encoded(report[branch]),
                    "passive allocation HTML changed saved branch: " + branch)
        for index, phase in enumerate(allocation["phases"]):
            require(encoded(fragments[f"/root_allocation/phases/{index}"])
                    == encoded(phase),
                    "passive allocation HTML changed a saved phase")
        allocation_reports[label] = report
        retained_allocation_inputs[path] = body

    peers = {}
    for label, options, version in (("default", [], 1),
                                     ("v2", ["--final-action-rule", "mean_visits"], 2)):
        path = outputs / ("root-allocation-peer-" + label + ".json")
        body = call("decide_episode.py",
                    [*allocation_arguments, "--sims", "32", *options], path.name)
        peers[label] = json.loads(body)
        require(
            peers[label]["schema_version"] == version
            and peers[label]["implementation"]["engine_files_sha256"]
            == installed_files,
            "ordinary report version or installed source changed")
        comparison = call(
            "inspect_episode.py",
            [str(outputs / "root-allocation-halving.json"), "--decision-report",
             "--compare-report", str(path)],
            "root-allocation-" + label + "-comparison.html", passive=True,
        )
        fragments = saved_fragments(comparison)
        for side, value in (("left", allocation_reports["halving"]),
                            ("right", peers[label])):
            for branch in ("selected_state", "configuration", "work", "legal_actions",
                           "ranking", "recommendation", "implementation"):
                require(encoded(fragments[f"/{side}/{branch}"])
                        == encoded(value[branch]),
                        "passive mixed-version comparison changed saved JSON")
        require(encoded(fragments["/left/root_allocation"])
                == encoded(allocation_reports["halving"]["root_allocation"]),
                "mixed-version comparison lost the allocation treatment")
        retained_allocation_inputs[path] = body
    require(
        all(encoded(peers["default"][branch]) == encoded(peers["v2"][branch])
            for branch in
            ("selected_state", "legal_actions", "ranking", "recommendation", "work")),
        "default and explicit mean/visits changed the same-seed UCT decision")

    allocation_reference_path = outputs / "root-allocation-reference.json"
    allocation_reference_bytes = call(
        "reference_episode.py", [str(outputs / "root-allocation-halving.json")],
        allocation_reference_path.name,
    )
    allocation_reference = json.loads(allocation_reference_bytes)
    values = {
        (row["action"]["card_idx"], row["action"]["target_idx"]):
        Fraction(int(row["expected_value"]["numerator"]),
                 int(row["expected_value"]["denominator"]))
        for row in allocation_reference["evaluation"]["actions"]
    }
    recommendation = allocation_reference["diagnostics"]["recommendation"]
    choice = allocation_reports["halving"]["recommendation"]
    key = choice["card_idx"], choice["target_idx"]
    loss = max(values.values()) - values[key]
    reference_consumer = allocation_reference["implementation"]["decision_consumer"]
    require(
        allocation_reference["status"] == "complete"
        and allocation_reference["new_search_performed"] is False
        and encoded(allocation_reference["decision_report"])
        == encoded(allocation_reports["halving"])
        and allocation_reference["reference_engine_files_sha256"] == installed_files
        and reference_consumer["engine_import_kind"] == "site-packages"
        and reference_consumer["engine_files_sha256"] == installed_files
        and allocation_reference["diagnostics"]["same_statistics"] is None
        and recommendation["action"] == {"card_idx": key[0], "target_idx": key[1]}
        and recommendation["value_loss"] == {
            "numerator": str(loss.numerator), "denominator": str(loss.denominator)},
        "installed reference lost the actual schema-3 recommendation or exact loss",
    )
    reference_html = call(
        "reference_episode.py", [str(allocation_reference_path), "--inspect"],
        "root-allocation-reference.html", passive=True,
    )
    fragments = saved_fragments(reference_html)
    for branch in ("evaluation", "diagnostics", "decision_report"):
        require(encoded(fragments["/" + branch])
                == encoded(allocation_reference[branch]),
                "passive reference reader changed the saved allocation loss or origin")
    retained_allocation_inputs[allocation_reference_path] = allocation_reference_bytes
    for label, horizon, options in (
            ("horizon", 2, []),
            ("final-rule", 1, ["--final-action-rule", "mean_visits"]),
            ("stability", 1, ["--stability", "--seeds", "19", "23"])):
        arguments = [str(record), "--step", "0", "--seed", "19",
                     "--horizon", str(horizon), "--sims", "32",
                     "--root-allocation", "sequential_halving", *options]
        refusal_bytes = call(
            "decide_episode.py", arguments,
            "root-allocation-" + label + "-refused.json", 2, passive=True)
        require(refusal_bytes == b"",
                "unsupported allocation controls emitted an apparently complete report")
    allocation_acceptance = {
        "input_kind": "genuinely recorded bounded custom episode",
        "schema_version": 3, "default_schema_version": 1,
        "explicit_rule_schema_version": 2,
        "policy": "budget_aware_sequential_halving_v1",
        "installed_engine_map": installed_files,
        "halving_report": str(outputs / "root-allocation-halving.json"),
        "tiny_fallback_report": str(outputs / "root-allocation-tiny.json"),
        "guarded_zero_report": str(outputs / "root-allocation-zero.json"),
        "reference_report": str(allocation_reference_path),
        "passive_decision_and_reference_guards": True,
        "saved_json_fragments_checked": True,
        "unsupported_controls_refused_before_search": True,
        "installed_reference_recommendation_loss": recommendation["value_loss"],
        "independent_policy_quality_claim": False,
    }
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

    # This supplied state is modeled, with no episode, draw tape or recording
    # identity claimed. Exercise the added route through the relocated payload.
    adaptive_model = "independent_two_round_adaptive_binary53_shaped_v1"
    adaptive_format = "mcts-two-round-adaptive-reference-report"
    adaptive_state_path = companion / "examples" / "adaptive-state.json"
    adaptive_state_bytes = adaptive_state_path.read_bytes()
    adaptive_state = json.loads(adaptive_state_bytes)
    adaptive_options = [
        "--model", "two-round-adaptive", "--method", "adaptive-physical",
    ]
    adaptive_reports = []
    for label, seconds in (("a", "10"), ("b", "5")):
        raw = call(
            "reference_episode.py",
            [str(adaptive_state_path), "--state-input", *adaptive_options,
             "--max-transitions", "1000", "--max-per-action", "500",
             "--max-work-units", "3000", "--max-seconds", seconds],
            "adaptive-state-reference-" + label + ".json",
        )
        value = json.loads(raw)
        require(
            value["format"] == adaptive_format
            and value["schema_version"] == 1 and value["status"] == "complete"
            and value["model"] == adaptive_model
            and value["computation_method"] == "adaptive-physical"
            and value["decision_report"] is None
            and value["selected_state"] == adaptive_state
            and value["source_report"]["kind"] == "normalized-state"
            and value["source_report"]["sha256"]
            == hashlib.sha256(adaptive_state_bytes).hexdigest()
            and value["implementation"]["decision_consumer"]["engine_import_kind"]
            == "site-packages"
            and value["diagnostics"]["recommendation"] is None
            and value["diagnostics"]["same_statistics"] is None,
            "installed direct state route changed origin, model or selection meaning",
        )
        evaluation = value["evaluation"]
        require(
            evaluation["optimal_actions"] == [1]
            and len(evaluation["actions"]) == 3,
            "modeled adaptive witness lost its complete physical root choices",
        )
        variable = evaluation["actions"][1]
        require(
            variable["action"] == {"card_idx": 0, "target_idx": 0}
            and len(variable["observations"]) == 2,
            "variable-hit witness lost distinct complete observations",
        )
        selected_continuations = {}
        for observation in variable["observations"]:
            require(
                observation["root_hand_indices"] == [1]
                and observation["probability"] == {"numerator": "1", "denominator": "2"}
                and len(observation["continuations"]) == 2,
                "observation lost probability, copy identity or a legal alternative",
            )
            chosen = observation["continuations"][observation["chosen"]]
            selected_continuations[observation["state"]["enemies"][0]["hp"]] = (
                chosen["action"], chosen["root_card_idx"]
            )
        require(
            selected_continuations == {
                2: ({"card_idx": 0, "target_idx": 0}, 1),
                1: ({"card_idx": None, "target_idx": None}, None),
            },
            "second choice did not adapt while both alternatives remained legal",
        )
        adaptive_reports.append(value)
    require(
        adaptive_reports[0]["evaluation"]["actions"]
        == adaptive_reports[1]["evaluation"]["actions"],
        "cooperative deadline setting changed completed adaptive expectations",
    )
    adaptive_left = outputs / "adaptive-state-reference-a.json"
    adaptive_right = outputs / "adaptive-state-reference-b.json"
    retained_adaptive_reports = {
        path: path.read_bytes() for path in (adaptive_left, adaptive_right)
    }
    adaptive_html = call(
        "reference_episode.py", [str(adaptive_left), "--inspect"],
        "adaptive-state-reference.html", passive=True,
    )
    adaptive_fragments = saved_fragments(adaptive_html)
    require(
        adaptive_fragments["/evaluation"] == adaptive_reports[0]["evaluation"]
        and adaptive_fragments["/selected_state"] == adaptive_state
        and adaptive_fragments["/decision_report"] is None
        and b"<script" not in adaptive_html,
        "passive adaptive inspection changed saved state or complete policy map",
    )
    adaptive_comparison = call(
        "reference_episode.py",
        [str(adaptive_left), "--inspect", "--compare-report", str(adaptive_right)],
        "adaptive-state-comparison.html", passive=True,
    )
    comparison_fragments = saved_fragments(adaptive_comparison)
    require(
        comparison_fragments["/left/evaluation"] == adaptive_reports[0]["evaluation"]
        and comparison_fragments["/right/evaluation"]
        == adaptive_reports[1]["evaluation"]
        and b"Complete adaptive values share the same state and objective"
        in adaptive_comparison,
        "passive adaptive comparison changed retained policy maps",
    )
    for label, old in (("physical", left),
                       ("sum", outputs / "sum-small-reference.json")):
        compared = call(
            "reference_episode.py",
            [str(adaptive_left), "--inspect", "--compare-report", str(old)],
            "adaptive-cross-family-" + label + ".html", passive=True,
        )
        require(
            b"ineligible" in compared and b"report_families_differ" in compared,
            "different report families were offered a common quality ranking",
        )
    adaptive_refused = json.loads(call(
        "reference_episode.py",
        [str(adaptive_state_path), "--state-input", *adaptive_options,
         "--max-transitions", "1"],
        "adaptive-work-refused.json", 1,
    ))
    require(
        adaptive_refused["format"] == adaptive_format
        and adaptive_refused["failure"]["kind"] == "work_limit"
        and adaptive_refused["evaluation"] is None
        and adaptive_refused["diagnostics"] is None,
        "adaptive work refusal leaked accepted policy values",
    )
    call(
        "reference_episode.py",
        [str(outputs / "adaptive-work-refused.json"), "--inspect"],
        "adaptive-work-refused.html", passive=True,
    )

    # Match the existing saved-decision test's explicit modeled-envelope route.
    # These placeholders are stored input claims, never observed provenance.
    modeled_final = json.loads(adaptive_state_bytes)
    modeled_final["round_num"] = 2
    placeholder = "0" * 64
    modeled_episode = {
        "format": "mcts-episode-record", "schema_version": 1,
        "content": {"kind": "custom",
                    "cards": {"bytes": 1, "sha256": placeholder},
                    "scenarios": {"bytes": 1, "sha256": placeholder}},
        "scenario": {"name": "Modeled adaptive input, not recorded or replayed",
                     "environment_seed": 7, "deck": adaptive_state["hand"]},
        "initial_state": adaptive_state,
        "implementation": {
            "python": "Modeled stored interpreter",
            "python_implementation": "Modeled stored interpreter",
            "platform": "Modeled input, no recording run",
            "engine_import_kind": "site-packages", "distribution_version": None,
            "distribution_matches_import": False,
            "engine_files_sha256": {"engine/state.py": placeholder},
            "example_files_sha256": {"game/runner.py": placeholder},
            "entrypoint_files_sha256": {"episode.py": placeholder},
            "machine": "Modeled stored machine", "pointer_bits": 64,
            "python_full_version": "Modeled stored version", "python_build": ["", ""],
            "python_cache_tag": None, "rng_state_version": 3,
        },
        "configuration": {
            "method": "mcts", "mode": "serial_clockless", "search_seed": 11,
            "search_rng_mode": "seed_once_continue", "max_rounds": 1,
            "max_sims_per_decision": 8, "horizon_rounds": 2,
            "max_transitions_per_decision": 16, "exploration": 1.2,
            "time_budget_ms": None, "parallel": False, "workers": None,
            "priors": None,
            "policy_rng": {"scheme": "policy-v1", "seed": 0, "used_by_policy": False},
        },
        "environment_rng": {
            "checkpoint_scheme": "python-random-getstate-json-v1", "state_version": 3,
            "after_scenario_sha256": placeholder, "final_sha256": placeholder,
        },
        "steps": [{"index": 0, "round_num": 1, "state": adaptive_state,
                   "action": {"card_idx": None, "target_idx": None,
                              "label": "Modeled Pass, not an observed action"}}],
        "final": {"state": modeled_final, "score": 0.5, "terminal_result": None,
                  "rounds": 1, "termination": "round_limit"},
    }
    modeled_episode_path = write(
        "adaptive-modeled-episode.json", encoded(modeled_episode)
    )
    modeled_episode_bytes = modeled_episode_path.read_bytes()
    adaptive_decision_path = outputs / "adaptive-selected-decision.json"
    decision_bytes = call(
        "decide_episode.py",
        [str(modeled_episode_path), "--step", "0", "--seed", "19", "--sims", "16",
         "--horizon", "2", "--final-action-rule", "mean_visits"],
        adaptive_decision_path.name,
    )
    adaptive_selected = json.loads(call(
        "reference_episode.py", [str(adaptive_decision_path), *adaptive_options],
        "adaptive-selected-reference.json",
    ))
    require(
        adaptive_selected["status"] == "complete"
        and adaptive_selected["source_report"]["kind"] == "saved-decision"
        and adaptive_selected["decision_report"] == json.loads(decision_bytes)
        and adaptive_selected["selected_state"] == adaptive_state
        and adaptive_selected["diagnostics"]["recommendation"] is not None
        and set(adaptive_selected["diagnostics"]["same_statistics"])
        == {"mean_visits", "visits_mean"}
        and adaptive_selected["evaluation"]["actions"]
        == adaptive_reports[0]["evaluation"]["actions"],
        "saved modeled decision lost selection or common adaptive values",
    )
    selected_html = call(
        "reference_episode.py",
        [str(outputs / "adaptive-selected-reference.json"), "--inspect"],
        "adaptive-selected-reference.html", passive=True,
    )
    selected_fragments = saved_fragments(selected_html)
    require(
        selected_fragments["/evaluation"] == adaptive_selected["evaluation"]
        and selected_fragments["/diagnostics"] == adaptive_selected["diagnostics"]
        and selected_fragments["/decision_report"]
        == adaptive_selected["decision_report"],
        "passive selected-loss inspection changed saved values or search origin",
    )
    # The old calculation still refuses horizon two instead of upgrading itself.
    old_horizon = json.loads(call(
        "reference_episode.py", [str(adaptive_decision_path)],
        "adaptive-old-default-refused.json", 1, passive=True,
    ))
    require(old_horizon["failure"]["kind"] == "horizon_mismatch",
            "old default silently expanded to two-round calculation")
    new_horizon = json.loads(call(
        "reference_episode.py",
        [str(outputs / "decision-a.json"), *adaptive_options],
        "adaptive-horizon-refused.json", 1, passive=True,
    ))
    require(
        new_horizon["format"] == adaptive_format
        and new_horizon["failure"]["kind"] == "horizon_mismatch"
        and new_horizon["evaluation"] is None
        and new_horizon["diagnostics"] is None,
        "new adaptive route silently changed a retained search horizon",
    )
    unsupported_state = json.loads(adaptive_state_bytes)
    unsupported_state["hand"].extend(unsupported_state["hand"])
    unsupported_path = write(
        "adaptive-four-card-state.json", encoded(unsupported_state)
    )
    unsupported = json.loads(call(
        "reference_episode.py",
        [str(unsupported_path), "--state-input", *adaptive_options],
        "adaptive-subset-refused.json", 1,
    ))
    require(
        unsupported["failure"]["kind"] == "unsupported_state"
        and unsupported["evaluation"] is None and unsupported["diagnostics"] is None,
        "adaptive calculation discarded excess physical cards instead of refusing",
    )
    require(
        adaptive_state_path.read_bytes() == adaptive_state_bytes
        and modeled_episode_path.read_bytes() == modeled_episode_bytes
        and adaptive_decision_path.read_bytes() == decision_bytes
        and all(path.read_bytes() == body
                for path, body in retained_adaptive_reports.items()),
        "new installed journey changed a supplied or retained input",
    )
    adaptive_acceptance = {
        "kind": "supplied modeled state and modeled saved-decision input",
        "captured_encounter": False, "episode_recorded_or_replayed": False,
        "model": adaptive_model, "report_family": adaptive_format,
        "direct_state_report": str(adaptive_left),
        "saved_selected_report": str(outputs / "adaptive-selected-reference.json"),
        "observed_installed_engine": str(origin),
        "observation_dependent_second_choice_checked": True,
        "physical_copy_mapping_checked": True,
        "input_bytes_preserved": True, "passive_saved_fragments_checked": True,
        "one_round_family_comparison_ineligible_checked": True,
        "work_refusal_without_partial_values_checked": True,
        "subset_and_horizon_refusals_without_partial_values_checked": True,
        "selected_loss_and_same_statistics_present": True,
        "work": adaptive_reports[0]["evaluation"]["work"],
    }

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
    require(
        all(path.read_bytes() == body
            for path, body in retained_allocation_inputs.items()),
        "optional installed journey changed captured episode/report inputs")
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
        "adaptive_acceptance": adaptive_acceptance,
        "root_allocation_acceptance": allocation_acceptance,
        "accepted_prior_journey_preserved": True,
    }
    write("acceptance.json", encoded(summary))
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
