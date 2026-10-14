"""Run the fixed installed episode journey after native Linux admission.

The caller supplies this literal public worker, a matching wheel and the complete
companion. This worker establishes input consistency, not native ownership or
authentication. The separate Linux owner supplies those execution observations.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import sysconfig
import venv
import zipfile
from pathlib import Path

MIB = 1_048_576
ENGINE_NAMES = {
    "engine/" + name
    for name in (
        "__init__.py",
        "actions.py",
        "decider.py",
        "mcts.py",
        "parallel.py",
        "py.typed",
        "rules.py",
        "simulator.py",
        "state.py",
    )
}
REQUEST = {
    "rounds": 2,
    "sims": 2,
    "horizon": 1,
    "environment_seed": 81001,
    "search_seed": 82001,
}
ARTIFACT_NAMES = ("record.json", "replay.json", "consumer.json")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def identity(body: bytes) -> dict:
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def read(path: Path, limit: int) -> bytes:
    require(stat.S_ISREG(path.lstat().st_mode), "input is not an ordinary file")
    with path.open("rb") as stream:
        body = stream.read(limit + 1)
    require(len(body) <= limit, "input exceeds its byte allowance")
    return body


def encoded(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()


def write(path: Path, body: bytes) -> None:
    require(len(body) <= 2 * MIB, "consumer artifact exceeds 2 MiB")
    with path.open("xb") as sink:
        require(sink.write(body) == len(body), "incomplete consumer artifact")


def request_from(body: bytes) -> dict:
    value = json.loads(body)
    require(
        isinstance(value, dict) and set(value) == {"wheel", *REQUEST},
        "unsupported installed consumer request",
    )
    require(
        all(
            type(value[key]) is int and value[key] == expected
            for key, expected in REQUEST.items()
        ),
        "installed consumer uses the fixed operational allowance and seeds",
    )
    wheel = value["wheel"]
    require(
        isinstance(wheel, str)
        and re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", wheel) is not None
        and len(wheel) <= 240
        and wheel.count("-") >= 4,
        "use the original valid wheel basename",
    )
    return value


def unpack(archive_path: Path, destination: Path, worker_body: bytes) -> dict:
    """Check all literal members before creating the extraction destination."""
    read(archive_path, 16 * MIB)
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        require(
            len(names) <= 256 and len(names) == len(set(names)),
            "companion has duplicate or excessive members",
        )
        require("manifest.json" in names, "companion manifest is absent")
        total = 0
        for member in members:
            parts = member.filename.split("/")
            mode = stat.S_IFMT(member.external_attr >> 16)
            require(
                all(part not in {"", ".", ".."} for part in parts)
                and not any(char in member.filename for char in "\\:")
                and mode in (0, stat.S_IFREG)
                and member.file_size <= MIB,
                "unsafe or excessive companion member",
            )
            total += member.file_size
        require(total <= 8 * MIB, "expanded companion exceeds 8 MiB")
        manifest = json.loads(archive.read("manifest.json"))
        require(
            isinstance(manifest, dict)
            and manifest.get("format") == "mcts-recording-companion"
            and type(manifest.get("schema_version")) is int
            and manifest["schema_version"] == 1
            and manifest.get("derived_documents") == {},
            "unsupported literal companion manifest",
        )
        for field in ("source_commit", "source_tree"):
            require(
                isinstance(manifest.get(field), str)
                and re.fullmatch(r"[0-9a-f]{40}", manifest[field]) is not None,
                "companion source identity is malformed",
            )
        payload = manifest.get("payload_files")
        require(
            isinstance(payload, dict)
            and set(names) == set(payload) | {"manifest.json"}
            and not any(
                name.startswith("engine/") or name.endswith(".whl") for name in payload
            ),
            "companion inventory differs",
        )
        reference = manifest.get("reference_engine")
        require(
            isinstance(reference, dict)
            and isinstance(reference.get("files"), dict)
            and set(reference["files"]) == ENGINE_NAMES,
            "companion does not declare the exact nine engine members",
        )
        require(
            payload.get("tools/linux_episode_worker.py") == identity(worker_body),
            "executing worker differs from its literal companion payload",
        )
        bodies = {}
        for name in names:
            body = archive.read(name)
            if name != "manifest.json":
                require(payload[name] == identity(body), "companion payload differs")
            bodies[name] = body
    destination.mkdir()
    for name, body in bodies.items():
        target = destination.joinpath(*name.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        write(target, body)
    return manifest


def bridge(
    companion: Path, entry: str, arguments: list[str], *, guard_search: bool = False
) -> list[str]:
    script = "import sys,runpy;sys.path.insert(0,sys.argv.pop(1));"
    if guard_search:
        script += (
            "import game.episode_record as records;import engine;"
            "import game.episode_decision as decisions;\n"
            "def refuse(*args,**kwargs):\n"
            " raise RuntimeError('SEARCH REACHED DURING SAVED ACTION REPLAY')\n"
            "records._record_owner=refuse;engine.mcts_decider=refuse;"
            "engine.MCTS.__init__=refuse;decisions.current_identity=refuse;"
            "decisions._reconstruct=refuse;"
        )
    script += "sys.argv=sys.argv[1:];runpy.run_path(sys.argv[0],run_name='__main__')"
    return [
        sys.executable,
        "-I",
        "-B",
        "-c",
        script,
        str(companion),
        str(companion / entry),
        *arguments,
    ]


def command(argv: list[str], working: Path, limit: int = 2 * MIB) -> bytes:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in {"PYTHONPATH", "PYTHONHOME"}
    }
    result = subprocess.run(
        argv,
        cwd=working,
        env=environment,
        shell=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=20,
    )
    require(
        len(result.stdout) <= limit and len(result.stderr) <= 65_536,
        "known consumer command exceeds retention allowance",
    )
    require(
        result.returncode == 0 and not result.stderr, "known consumer command failed"
    )
    return result.stdout


def installed_journey(payload: Path, request: dict, results: Path) -> None:
    import engine

    require(
        importlib.util.find_spec("game") is None,
        "installed wheel unexpectedly supplies game examples",
    )
    origin = Path(engine.__file__).resolve()
    purelib = Path(sysconfig.get_path("purelib")).resolve()
    require(
        origin.is_relative_to(purelib), "engine did not come from installed purelib"
    )
    distribution = importlib.metadata.distribution("mcts-combat-engine")
    require(
        Path(str(distribution.locate_file("engine"))).resolve() == origin.parent,
        "engine distribution and imported package differ",
    )
    journey = Path("/tmp/journey")
    journey.mkdir()
    initial = journey / "companion"
    manifest = unpack(payload / "companion.zip", initial, Path(__file__).read_bytes())
    companion = journey / "relocated-companion"
    initial.rename(companion)
    observed_engine = {}
    for name in ENGINE_NAMES:
        body = read(origin.parent / name.removeprefix("engine/"), MIB)
        observed_engine[name] = identity(body)
    require(
        observed_engine == manifest["reference_engine"]["files"],
        "installed engine differs from all nine literal source members",
    )
    observed_names = {
        "engine/" + path.relative_to(origin.parent).as_posix()
        for path in origin.parent.rglob("*")
        if path.is_file()
        and (path.suffix in {".py", ".pyd", ".so"} or path.name == "py.typed")
    }
    require(observed_names == ENGINE_NAMES, "installed engine member map differs")
    sys.path.insert(0, str(companion))
    modules = {
        name: importlib.import_module(name)
        for name in (
            "game",
            "game.loader",
            "game.episode_record",
            "game.episode_decision",
        )
    }
    game_origins = {
        name: str(Path(module.__file__).resolve()) for name, module in modules.items()
    }
    require(
        all(
            Path(path).is_relative_to(companion / "game")
            for path in game_origins.values()
        ),
        "game examples were not relocated",
    )
    inputs = journey / "inputs"
    inputs.mkdir()
    cards = inputs / "cards.json"
    scenarios = inputs / "scenarios.json"
    write(
        cards,
        encoded(
            {
                "cards": [
                    {
                        "name": "Pulse",
                        "element": "ember",
                        "type": "damage",
                        "pip_cost": 0,
                        "accuracy": 1.0,
                        "damage_min": 1,
                        "damage_max": 1,
                    }
                ]
            }
        ),
    )
    write(
        scenarios,
        encoded(
            {
                "scenarios": {
                    "linux-consumer": {
                        "player": {
                            "name": "Operator",
                            "element": "ember",
                            "hp": 100,
                            "power_pip_chance": 0.0,
                        },
                        "deck": ["Pulse"],
                        "enemies": [
                            {
                                "name": "Target",
                                "element": "frost",
                                "hp": 100,
                                "power_pip_chance": 0.0,
                                "attack": {
                                    "name": "Reply",
                                    "element": "frost",
                                    "type": "damage",
                                    "pip_cost": 14,
                                    "accuracy": 1.0,
                                    "damage_min": 1,
                                    "damage_max": 1,
                                },
                            }
                        ],
                    }
                }
            }
        ),
    )
    before = {
        path.name: {**identity(path.read_bytes()), "mtime_ns": path.stat().st_mtime_ns}
        for path in (cards, scenarios)
    }
    working = journey / "unrelated-working-directory"
    working.mkdir()
    content = ["--cards", str(cards), "--scenarios", str(scenarios)]
    body = command(
        bridge(
            companion,
            "episode.py",
            [
                "record",
                "linux-consumer",
                *content,
                "--rounds",
                str(request["rounds"]),
                "--sims",
                str(request["sims"]),
                "--horizon",
                str(request["horizon"]),
                "--environment-seed",
                str(request["environment_seed"]),
                "--search-seed",
                str(request["search_seed"]),
                "--root-allocation",
                "uct",
            ],
        ),
        working,
    )
    record = json.loads(body)
    require(
        record["schema_version"] == 2
        and len(record["steps"]) == 2
        and record["final"]["termination"] == "round_limit"
        and record["final"]["terminal_result"] is None,
        "fixed consumer did not reach its declared nonterminal round cap",
    )
    require(
        all(
            step["work"]["simulations"] == 2 and step["work"]["transitions"] == 2
            for step in record["steps"]
        ),
        "fixed consumer did not complete its literal four simulations/transitions",
    )
    implementation = record["implementation"]
    require(
        implementation["engine_import_kind"] == "site-packages"
        and implementation["distribution_matches_import"] is True
        and implementation["engine_files_sha256"]
        == {
            name.removeprefix("engine/"): item["sha256"]
            for name, item in observed_engine.items()
        },
        "record did not observe the separately installed exact engine",
    )
    record_path = results / "record.json"
    write(record_path, body)
    replay_body = command(
        bridge(
            companion,
            "episode.py",
            ["replay", str(record_path), *content],
            guard_search=True,
        ),
        working,
    )
    replay = json.loads(replay_body)
    require(
        replay["status"] == "environment_replay_verified"
        and replay["search_recomputed"] is False,
        "guarded saved-action replay was not verified",
    )
    write(results / "replay.json", replay_body)
    after = {
        path.name: {**identity(path.read_bytes()), "mtime_ns": path.stat().st_mtime_ns}
        for path in (cards, scenarios)
    }
    require(before == after, "custom input bytes or mtimes changed")
    write(
        results / "consumer.json",
        encoded(
            {
                "format": "mcts-installed-linux-consumer",
                "schema_version": 1,
                "status": "complete",
                "source_commit": manifest["source_commit"],
                "source_tree": manifest["source_tree"],
                "request": request,
                "engine_origin": str(origin),
                "purelib": str(purelib),
                "engine_files": observed_engine,
                "game_module_origins": game_origins,
                "companion_origin": str(companion),
                "payload_count": len(manifest["payload_files"]),
                "inputs_before": before,
                "inputs_after": after,
                "record": identity(body),
                "replay": identity(replay_body),
                "actual_rounds": 2,
                "actual_simulations": 4,
                "actual_transitions": 4,
                "search_guarded_replay": True,
                "boundaries": {
                    "native_ownership_established_by_worker": False,
                    "origin_authenticated": False,
                    "scientific_inference": False,
                    "replay_scope": (
                        "saved actions and environment; search not recomputed"
                    ),
                },
            }
        ),
    )


def main() -> int:
    payload = Path(__file__).resolve().parent
    request = request_from(read(payload / "request.json", 4096))
    if sys.argv[1:] == ["--installed"]:
        results = Path("/tmp/results")
        results.mkdir(exist_ok=True)
        require(
            stat.S_ISDIR(results.lstat().st_mode) and not any(results.iterdir()),
            "consumer results must be an ordinary empty directory",
        )
        installed_journey(payload, request, results)
        result = encoded({"status": "complete", "artifacts": list(ARTIFACT_NAMES)})
        print(result.decode(), end="", flush=True)
        return 0
    require(not sys.argv[1:], "unsupported worker arguments")
    require(
        sys.platform == "linux" and os.geteuid() != 0,
        "worker requires the admitted nonroot Linux container",
    )
    # Validate the selected archive and worker before installation admission.
    checked = Path("/tmp/checked-companion")
    unpack(payload / "companion.zip", checked, Path(__file__).read_bytes())
    read(payload / request["wheel"], 16 * MIB)
    environment = Path("/tmp/install")
    # /tmp is noexec. These interpreter links resolve to the image's trusted
    # executable rather than copying an executable onto that tmpfs.
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    command(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--python",
            str(environment / "bin/python"),
            "install",
            "--no-index",
            "--no-deps",
            "--no-compile",
            str(payload / request["wheel"]),
        ],
        payload,
        65_536,
    )
    output = command(
        [
            str(environment / "bin/python"),
            "-I",
            "-B",
            str(Path(__file__).resolve()),
            "--installed",
        ],
        payload,
        65_536,
    )
    print(output.decode(), end="", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
