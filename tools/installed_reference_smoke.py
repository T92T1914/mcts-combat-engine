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
    require(cards.read_bytes() == original, "accepted card input changed")
    summary = {
        "installed_engine": str(origin),
        "companion_source": prior["companion_source"],
        "receipts": receipts,
        "root": str(root),
        "recorded_supported_episode": str(record),
        "accepted_prior_journey_preserved": True,
    }
    write("acceptance.json", encoded(summary))
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
