"""Supply a small installed consumer to an explicitly selected Linux owner."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from tools import linux_container as owner
from tools import linux_enforcement_preflight as preflight

MAX_INPUT = 16 * 1_048_576
MAX_FILES = 256
WORKER = "tools/linux_episode_worker.py"
ARTIFACTS = ("record.json", "replay.json", "consumer.json")


def identity(body: bytes) -> dict:
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def encoded(value: dict) -> bytes:
    text = json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    return text.encode()


def ordinary(path: Path, maximum: int) -> tuple[bytes, tuple[int, int, int, int]]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
        raise ValueError("input is not an admitted ordinary bounded file")
    with path.open("rb") as stream:
        body = stream.read(maximum + 1)
    after = path.lstat()
    stamp = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    if len(body) > maximum or stamp != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("input changed during its bounded read")
    return body, stamp


def companion_worker(body: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) > MAX_FILES or len(names) != len(set(names)):
            raise ValueError("companion inventory exceeds its allowance or repeats")
        total = 0
        for entry in entries:
            name = entry.filename
            parts = PurePosixPath(name).parts
            if (not parts or name.startswith("/") or "\\" in name or ":" in name or
                    any(part in ("", ".", "..") for part in name.split("/")) or
                    entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError("companion contains an unsupported member")
            total += entry.file_size
            if total > MAX_INPUT or entry.file_size > MAX_INPUT:
                raise ValueError("companion expanded bytes exceed their allowance")
        manifest = json.loads(archive.read("manifest.json"))
        if not isinstance(manifest, dict):
            raise ValueError("companion manifest must be an object")
        payload = manifest.get("payload_files")
        if not isinstance(payload, dict):
            raise ValueError("companion payload inventory must be an object")
        if (manifest.get("format") != "mcts-recording-companion" or
                manifest.get("schema_version") != 1 or
                set(names) != set(payload) | {"manifest.json"} or
                any(name.startswith("engine/") or name.endswith(".whl")
                    for name in names)):
            raise ValueError("companion manifest or distribution differs")
        for name, expected in payload.items():
            if (not isinstance(expected, dict) or type(expected.get("bytes")) is not int
                    or identity(archive.read(name)) != expected):
                raise ValueError("companion payload identity differs: " + name)
        return archive.read(WORKER)


def write_new(path: Path, body: bytes) -> None:
    with path.open("xb") as stream:
        if stream.write(body) != len(body):
            raise OSError("short output write")


def available() -> bool:
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        preflight.main()
    return json.loads(captured.getvalue()).get("disposition") == \
        "existing_docker_candidate"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--companion", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-id", help="already acquired immutable Docker image ID")
    parser.add_argument("--wall-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    try:
        if not available():
            print("Linux ownership unavailable; no workload admitted.")
            return 2
        if not 1 <= args.wall_seconds <= 30:
            raise ValueError("wall allowance must be between 1 and 30 seconds")
        if (not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", args.wheel.name) or
                len(args.wheel.name) > 240 or args.wheel.name.count("-") < 4):
            raise ValueError("engine wheel needs its original valid basename")
        wheel, wheel_stamp = ordinary(args.wheel, MAX_INPUT)
        archive, archive_stamp = ordinary(args.companion, MAX_INPUT)
        worker = companion_worker(archive)
        if len(wheel) + len(archive) + len(worker) > MAX_INPUT:
            raise ValueError("consumer payload exceeds its input allowance")
        image = args.image_id or owner.acquire_image()
        output = args.output.absolute()
        output.mkdir(exist_ok=False)
        journal = output / "ownership.json"

        def retain(receipt: dict) -> None:
            body = encoded(receipt)
            if len(body) > 131_072:
                raise ValueError("ownership receipt exceeds its control allowance")
            pending = output / "ownership.pending"
            write_new(pending, body)
            os.replace(pending, journal)

        with tempfile.TemporaryDirectory(prefix="mcts-linux-payload-") as staging:
            payload = Path(staging)
            write_new(payload / args.wheel.name, wheel)
            write_new(payload / "companion.zip", archive)
            write_new(payload / "worker.py", worker)
            write_new(payload / "request.json", encoded({
                "wheel": args.wheel.name, "rounds": 2, "sims": 2, "horizon": 1,
                "environment_seed": 81001, "search_seed": 82001,
            }))
            result = owner.run_owned_container(
                payload, ["python3", "-I", "-B", "/tmp/payload/worker.py"],
                image_id=image, receipt_callback=retain,
                wall_seconds=args.wall_seconds, stdout_limit=65_536,
                stderr_limit=65_536, output_limit=131_072, artifact_names=ARTIFACTS)
        for name, body in result.pop("streams", {}).items():
            if name not in ("stdout", "stderr"):
                raise ValueError("unexpected output stream")
            write_new(output / (name + ".log"), body)
        for name, body in result.pop("artifacts", {}).items():
            if name not in ARTIFACTS:
                raise ValueError("unexpected consumer artifact")
            write_new(output / name, body)
        unchanged = ordinary(args.wheel, MAX_INPUT) == (wheel, wheel_stamp) and \
            ordinary(args.companion, MAX_INPUT) == (archive, archive_stamp)
        result["input_files_unchanged"] = unchanged
        if not unchanged:
            result["outcome"] = {"status": "incomplete", "returncode": None,
                                 "reason": "original input file changed"}
        retain(result)
        print(json.dumps({"output": str(output), "outcome": result["outcome"],
                          "cleanup": result["cleanup"],
                          "input_files_unchanged": unchanged}, sort_keys=True))
        return 0 if unchanged and result["outcome"]["status"] == "complete" else 1
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as error:
        print("Linux episode: " + str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
