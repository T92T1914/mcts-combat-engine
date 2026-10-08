"""Build the saved-episode examples from clean, literal committed source."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP_NAME = "episode-examples.zip"
SIDECAR_NAME = ZIP_NAME + ".sha256"
OUTPUT_NAMES = {ZIP_NAME, SIDECAR_NAME}
MIB = 1_048_576
MEMBER_BYTES = MIB
PAYLOAD_BYTES = 8 * MIB
ZIP_BYTES = 16 * MIB
PAYLOAD_MEMBERS = 128
FIXED_PAYLOAD = {
    "inspect_episode.py", "decide_episode.py", "LICENSE",
    "docs/episode-inspection.md", "docs/episode-decision.md",
    "docs/episode-example-kit.md",
}
ENGINE_NAMES = {"engine/" + name for name in (
    "__init__.py", "actions.py", "decider.py", "mcts.py", "parallel.py",
    "py.typed", "rules.py", "simulator.py", "state.py",
)}
GUIDE = "docs/episode-inspection.md"
REPLAY_MARKER = b"(episode-record-replay.md)"


class KitError(ValueError):
    """Source or output cannot be accepted as an example kit."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise KitError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def identity(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": digest(data)}


def _git(root: Path, *args: str, data: bytes | None = None,
         limit: int = MIB) -> bytes:
    command = ["git", "--no-optional-locks", "--no-replace-objects",
               "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
               "-C", str(root), *args]
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith("GIT_")}
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    context = "git " + args[0]
    try:
        result = subprocess.run(
            command, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, shell=False, env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise KitError(context + " failed: " + str(error)) from error
    require(result.returncode == 0, context + " failed: " +
            result.stderr[:1024].decode("utf-8", "replace").strip())
    require(len(result.stdout) <= limit and len(result.stderr) <= 4096,
            context + " returned oversized metadata or content")
    return result.stdout


def _revision(root: Path) -> tuple[str, str]:
    commit = _git(root, "rev-parse", "--verify", "HEAD").decode("ascii").strip()
    tree = _git(root, "rev-parse", "--verify", commit + "^{tree}")
    tree_name = tree.decode("ascii").strip()
    require(bool(re.fullmatch(r"[0-9a-f]{40}", commit)) and
            bool(re.fullmatch(r"[0-9a-f]{40}", tree_name)),
            "expected full SHA-1 commit and tree identities")
    require(not _git(root, "status", "--porcelain=v1", "--untracked-files=all"),
            "source must have no tracked or nonignored untracked changes")
    return commit, tree_name


def _safe_name(name: str) -> None:
    parts = name.split("/")
    require(bool(name) and len(name.encode("utf-8")) <= 512 and
            all(part not in {"", ".", ".."} for part in parts) and
            not any(character in name for character in '\\:<>"|?*') and
            all(ord(character) >= 32 and not 127 <= ord(character) <= 159
                for character in name),
            "unsafe archive/source name: " + repr(name))
    for part in parts:
        require(not part.endswith((".", " ")) and not re.fullmatch(
            r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", part.split(".")[0].upper()),
            "unsupported portable name: " + repr(name))


def _inventory(root: Path, commit: str) -> tuple[dict, tuple[str, ...]]:
    listing = _git(root, "ls-tree", "-rlz", "--full-tree", commit, "--",
                   *sorted(FIXED_PAYLOAD), "game/", "engine/", "pyproject.toml")
    rows: dict[str, tuple[str, int]] = {}
    folded: set[str] = set()
    for item in listing.split(b"\0"):
        if not item:
            continue
        header, encoded = item.split(b"\t", 1)
        name = encoded.decode("utf-8")
        _safe_name(name)
        mode, kind, oid, size = header.decode("ascii").split()
        require(mode in {"100644", "100755"} and kind == "blob" and
                bool(re.fullmatch(r"[0-9a-f]{40}", oid)) and size.isdecimal(),
                "nonregular committed member: " + name)
        require(name not in rows and name.casefold() not in folded,
                "duplicate portable member: " + name)
        length = int(size)
        require(length <= MEMBER_BYTES, "member exceeds 1 MiB: " + name)
        rows[name] = (oid, length)
        folded.add(name.casefold())
    game = {name for name in rows if name.startswith("game/")}
    require(bool(game) and "game/__init__.py" in game and
            all(name.endswith(".py") for name in game),
            "complete game directory must contain only committed Python files")
    require({name for name in rows if name.startswith("engine/")} == ENGINE_NAMES,
            "reference engine inventory differs from the nine supported members")
    payload = FIXED_PAYLOAD | game
    require(set(rows) == payload | ENGINE_NAMES | {"pyproject.toml"},
            "missing or unexpected source member")
    require(len(payload) <= PAYLOAD_MEMBERS and
            sum(rows[name][1] for name in payload) <= PAYLOAD_BYTES,
            "payload inventory exceeds its member or byte allowance")
    return rows, tuple(sorted(payload, key=lambda name: name.encode("utf-8")))


def _blobs(root: Path, rows: dict) -> dict[str, bytes]:
    names = sorted(rows, key=lambda name: name.encode("utf-8"))
    request = "".join(rows[name][0] + "\n" for name in names).encode("ascii")
    limit = sum(rows[name][1] for name in names) + 128 * len(names)
    response = _git(root, "cat-file", "--batch", data=request, limit=limit)
    cursor = 0
    result = {}
    for name in names:
        end = response.find(b"\n", cursor)
        require(end >= cursor, "missing Git blob header: " + name)
        header = response[cursor:end].decode("ascii").split()
        oid, length = rows[name]
        require(header == [oid, "blob", str(length)], "Git blob header differs")
        cursor = end + 1
        body = response[cursor:cursor + length]
        cursor += length
        require(len(body) == length and response[cursor:cursor + 1] == b"\n",
                "truncated Git blob: " + name)
        expected_oid = hashlib.sha1(
            b"blob " + str(length).encode("ascii") + b"\0" + body
        ).hexdigest()
        require(expected_oid == oid, "literal Git blob identity differs: " + name)
        cursor += 1
        result[name] = body
    require(cursor == len(response), "unexpected trailing Git blob content")
    return result


def _ordinary(info, *, directory: bool = False) -> bool:
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(
        info.st_mode)
    return bool(expected and not getattr(info, "st_file_attributes", 0) &
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024))


def _raw(root: Path, name: str) -> bytes:
    path = root
    for part in name.split("/")[:-1]:
        path /= part
        require(_ordinary(path.lstat(), directory=True),
                "nonordinary source directory: " + name)
    path = root.joinpath(*name.split("/"))
    require(_ordinary(path.lstat()), "nonordinary source file: " + name)
    with path.open("rb") as stream:
        body = stream.read(MEMBER_BYTES + 1)
    require(len(body) <= MEMBER_BYTES, "raw source exceeds 1 MiB: " + name)
    return body


@dataclass(frozen=True)
class Source:
    root: Path
    commit: str
    tree: str
    payload: tuple[str, ...]
    blobs: dict[str, bytes]
    raw: dict[str, bytes]


def _source(root: Path) -> Source:
    root = root.resolve()
    top = _git(root, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    require(Path(top).resolve() == root, "generator needs the Git checkout root")
    commit, tree = _revision(root)
    rows, payload = _inventory(root, commit)
    bodies = _blobs(root, rows)
    raw = {}
    for name, body in bodies.items():
        captured = _raw(root, name)
        if captured != body:
            captured.decode("utf-8")
            body.decode("utf-8")
            require(captured.replace(b"\r\n", b"\n") == body,
                    "raw source differs beyond UTF-8 CRLF conversion: " + name)
        raw[name] = captured
    return Source(root, commit, tree, payload, bodies, raw)


def _emitted(source: Source) -> tuple[dict[str, bytes], dict]:
    payload = {name: source.blobs[name] for name in source.payload}
    guide = payload[GUIDE]
    require(guide.count(REPLAY_MARKER) == 1,
            "inspection guide must contain exactly one replay Markdown target")
    target = ("(https://github.com/T92T1914/mcts-combat-engine/blob/" +
              source.commit + "/docs/episode-record-replay.md)")
    payload[GUIDE] = guide.replace(REPLAY_MARKER, target.encode("ascii"))
    require(len(payload[GUIDE]) <= MEMBER_BYTES and
            sum(map(len, payload.values())) <= PAYLOAD_BYTES,
            "derived payload exceeds its byte allowance")
    project_text = source.blobs["pyproject.toml"].decode("utf-8")
    try:
        project = tomllib.loads(project_text)
    except ValueError as error:
        raise KitError("reference project metadata could not be parsed: " +
                       str(error)) from error
    package = project.get("project")
    if not isinstance(package, dict):
        raise KitError("reference project metadata must be a table")
    require(package["name"] == "mcts-combat-engine" and
            package["version"] == "0.1.0" and
            package["requires-python"] == ">=3.11" and
            package["dependencies"] == [], "reference package metadata differs")
    manifest = {
        "format": "mcts-saved-episode-example-kit", "schema_version": 1,
        "source_commit": source.commit, "source_tree": source.tree,
        "payload_files": {name: identity(body) for name, body in payload.items()},
        "reference_engine": {
            "files": {name: identity(source.blobs[name])
                      for name in sorted(ENGINE_NAMES)},
            "package": {key: package[key] for key in
                        ("name", "version", "requires-python", "dependencies")},
        },
        "derived_documents": {GUIDE: {
            "canonical": identity(guide), "emitted": identity(payload[GUIDE]),
            "transformation": {"kind": "single_markdown_target",
                               "from": REPLAY_MARKER.decode("ascii"),
                               "to": target},
        }},
    }
    return payload, manifest


def _archive(payload: dict[str, bytes], manifest: dict) -> bytes:
    members = dict(payload)
    members["manifest.json"] = (json.dumps(
        manifest, ensure_ascii=True, sort_keys=True, indent=2
    ) + "\n").encode("utf-8")
    require(len(members["manifest.json"]) <= MEMBER_BYTES,
            "manifest exceeds 1 MiB")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED,
                         allowZip64=False) as archive:
        for name in sorted(members, key=lambda value: value.encode("utf-8")):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.create_version = info.extract_version = 20
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.internal_attr = 0
            info.compress_type = zipfile.ZIP_STORED
            info.comment = info.extra = b""
            archive.writestr(info, members[name])
    data = buffer.getvalue()
    require(len(data) <= ZIP_BYTES, "completed ZIP exceeds 16 MiB")
    return data


def _reobserve(source: Source) -> None:
    require(_revision(source.root) == (source.commit, source.tree),
            "source revision changed during generation")
    require(all(_raw(source.root, name) == body
                for name, body in source.raw.items()),
            "selected raw source changed during generation")


def prepare(root: Path) -> tuple[bytes, bytes, dict]:
    """Capture canonical source and buffer both outputs before writing either."""
    try:
        source = _source(root)
        payload, manifest = _emitted(source)
        archive = _archive(payload, manifest)
        sidecar = (digest(archive) + "  " + ZIP_NAME + "\n").encode("ascii")
        _reobserve(source)
        return archive, sidecar, manifest
    except (OSError, UnicodeError, KeyError, tomllib.TOMLDecodeError) as error:
        raise KitError("source could not be captured: " + str(error)) from error


def _output_directory(root: Path) -> Path:
    output = root.resolve() / "_site"
    if output.exists() or output.is_symlink():
        require(_ordinary(output.lstat(), directory=True),
                "kit output directory must be ordinary _site")
    else:
        output.mkdir()
    for name in OUTPUT_NAMES:
        path = output / name
        if path.exists() or path.is_symlink():
            info = path.lstat()
            require(_ordinary(info) and info.st_nlink == 1,
                    "owned kit output must be an ordinary single-link file")
    return output


def build(root: Path = ROOT) -> dict:
    """Write only the ZIP and sidecar; failure of either write propagates."""
    archive, sidecar, manifest = prepare(root)
    try:
        output = _output_directory(root)
        for name, data in ((ZIP_NAME, archive), (SIDECAR_NAME, sidecar)):
            with (output / name).open("wb") as stream:
                written = stream.write(data)
                require(written == len(data), "incomplete owned output: " + name)
        return {"manifest": manifest, "files": {
            ZIP_NAME: identity(archive), SIDECAR_NAME: identity(sidecar)}}
    except OSError as error:
        raise KitError("kit output write failed: " + str(error)) from error


def main() -> int:
    try:
        build(ROOT)
    except (KitError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        print("Example kit: " + str(error), file=sys.stderr)
        return 1
    print("Built " + ZIP_NAME + " and " + SIDECAR_NAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
