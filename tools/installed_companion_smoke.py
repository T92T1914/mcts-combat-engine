"""Witness a relocated companion against an external installed engine.

The caller supplies a fresh external destination and an outer process timeout.
This acceptance helper is not included in either public example distribution.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import sysconfig
import zipfile
from pathlib import Path

import engine


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def write(path: Path, body: bytes) -> None:
    with path.open("xb") as stream:
        require(stream.write(body) == len(body), "short fixture/artifact write")


def encoded(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    origin = Path(engine.__file__).resolve()
    purelib = Path(sysconfig.get_path("purelib")).resolve()
    require(origin.is_relative_to(purelib), "engine did not come from the installation")
    require(importlib.util.find_spec("game") is None,
            "engine install contains examples")
    root = args.destination.absolute()
    root.mkdir(exist_ok=False)
    companion = root / "companion"
    companion.mkdir()
    with zipfile.ZipFile(args.archive) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        expected = set(manifest["payload_files"]) | {"manifest.json"}
        require(set(archive.namelist()) == expected, "archive inventory differs")
        require(manifest["format"] == "mcts-recording-companion", "wrong distribution")
        require(not any(name.startswith("engine/") or name.endswith(".whl")
                        for name in expected), "companion contains engine code")
        for name in expected:
            parts = name.split("/")
            require(all(part not in {"", ".", ".."} for part in parts) and
                    not any(char in name for char in "\\:"), "unsafe archive name")
            body = archive.read(name)
            if name != "manifest.json":
                require(manifest["payload_files"][name] == {
                    "bytes": len(body), "sha256": digest(body)}, "payload hash differs")
            target = companion.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            write(target, body)
    for name, identity in manifest["reference_engine"]["files"].items():
        body = origin.parent.joinpath(*name.split("/")[1:]).read_bytes()
        require(identity == {"bytes": len(body), "sha256": digest(body)},
                "installed reference engine differs: " + name)
    inputs = root / "inputs"
    inputs.mkdir()
    cards = inputs / "cards.json"
    scenarios = inputs / "scenarios.json"
    write(cards, encoded({"cards": [{
        "name": "Pulse", "element": "ember", "type": "damage", "accuracy": 1.0,
        "damage_min": 20, "damage_max": 30, "dot_tick": 2, "dot_rounds": 2,
    }]}))
    write(scenarios, encoded({"scenarios": {"trial": {
        "player": {"name": "Operator", "element": "ember", "hp": 10000,
                   "power_pip_chance": 0.4}, "deck": ["Pulse"],
        "enemies": [{"name": "Target", "element": "frost", "hp": 1000,
                     "is_boss": True, "attack": {"name": "Reply", "element": "frost",
                     "type": "damage", "accuracy": 0.8, "damage_min": 1,
                     "damage_max": 2}, "rules": [{"type": "punish_traps"},
                     {"type": "enrage_below_half", "blade": 0.2}]}],
    }}}))
    retained = {path: path.read_bytes() for path in (cards, scenarios)}
    working = root / "unrelated-working-directory"
    working.mkdir()
    outputs = root / "results"
    outputs.mkdir()
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() not in {"PYTHONPATH", "PYTHONHOME"}}
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    receipts = []

    def call(entry: str, arguments: list[str], output: str, status: int = 0,
             *, guard_search: bool = False) -> bytes:
        command = [sys.executable, "-E", "-s", "-B", str(companion / entry), *arguments]
        if guard_search:
            script = (
                "import sys,runpy;sys.path.insert(0,sys.argv.pop(1));"
                "import game.episode_record as records;import engine;"
                "\n"
                "def refuse(*args,**kwargs):\n"
                " raise RuntimeError('SEARCH REACHED DURING REPLAY')\n"
                "records._record_owner=refuse;engine.mcts_decider=refuse;"
                "sys.argv=sys.argv[1:];runpy.run_path(sys.argv[0],run_name='__main__')"
            )
            command = [sys.executable, "-I", "-B", "-c", script,
                       str(companion), str(companion / entry), *arguments]
        result = subprocess.run(command, cwd=working, env=environment,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=20, shell=False,
                                creationflags=getattr(subprocess,
                                                      "CREATE_NO_WINDOW", 0))
        require(result.returncode == status,
                entry + " returned " + str(result.returncode) + ": " +
                result.stderr.decode("utf-8", "replace"))
        require(not result.stderr if status == 0 else
                bool(result.stderr) or bool(result.stdout),
                "unexpected diagnostic contract")
        require(result.stdout.endswith(b"\n") and b"\r\n" not in result.stdout
                if status in {0, 3} else not result.stdout,
                "incomplete/LF output contract")
        write(outputs / output, result.stdout)
        receipts.append({"entry": entry, "output": output, "status": status,
                         "bytes": len(result.stdout), "sha256": digest(result.stdout),
                         "search_guarded": guard_search})
        return result.stdout

    content = ["--cards", str(cards), "--scenarios", str(scenarios)]
    record_body = call("episode.py", ["record", "trial", *content,
                       "--rounds", "3", "--sims", "2", "--horizon", "1"],
                       "episode.json")
    record = json.loads(record_body)
    require(record["implementation"]["engine_import_kind"] == "site-packages",
            "record did not observe installed engine")
    require(len(record["steps"]) == 3, "fixture did not reach its round bound")
    record_path = outputs / "episode.json"
    moved = root / "relocated-companion"
    companion.rename(moved)
    companion = moved
    replay = json.loads(call("episode.py", ["replay", str(record_path), *content],
                             "replay.json", guard_search=True))
    require(replay["status"] == "environment_replay_verified" and
            replay["search_recomputed"] is False,
            "saved episode did not replay without search")
    call("inspect_episode.py", [str(record_path), "--appearance", "obscur"],
         "episode.html")
    for label, seed in (("a", "19"), ("b", "23")):
        report = json.loads(call("decide_episode.py", [str(record_path), "--step", "0",
                            "--seed", seed, "--sims", "2", "--horizon", "1"],
                            "decision-" + label + ".json"))
        require(report["search_performed"] is True,
                "fresh bounded search not performed")
    left, right = outputs / "decision-a.json", outputs / "decision-b.json"
    call("inspect_episode.py", [str(left), "--decision-report",
         "--appearance", "obscur"],
         "decision.html")
    comparison = call("inspect_episode.py", [str(left), "--decision-report",
                      "--compare-report", str(right), "--appearance", "obscur"],
                      "comparison.html")
    require(b'data-comparison-status=' in comparison,
            "comparison omitted retained differences")
    incompatible = json.loads(record_body)
    incompatible["implementation"]["python"] = "historical-runtime-label"
    incompatible_path = outputs / "historical-runtime.json"
    write(incompatible_path, encoded(incompatible))
    result = json.loads(call("episode.py", ["replay", str(incompatible_path), *content],
                             "incompatible.json", 3, guard_search=True))
    require(result["status"] == "incompatible", "historical identity rule was bypassed")
    call("episode.py", ["record", "trial", "--cards", str(cards)], "invalid.stdout", 2)
    require(all(path.read_bytes() == body for path, body in retained.items()),
            "custom input bytes changed")
    summary = {"installed_engine": str(origin),
               "companion_source": manifest["source_commit"],
               "destination": str(root), "relocated": True, "receipts": receipts}
    write(root / "acceptance.json", encoded(summary))
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
