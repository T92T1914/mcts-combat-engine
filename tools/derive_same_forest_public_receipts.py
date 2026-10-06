"""Create the two declared public receipt derivatives from retained private inputs."""

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPLETE = (
    "same-forest-repeatability-public-receipts.json",
    2898540,
    "552342df0e7800d85a2b092f0a33f03d147323b91081e5e56d9f594329bb4160",
)
FAILED = (
    "same-forest-repeatability-public-failed-attempt.json",
    19193,
    "807583e64f0affd853ae4c34651e9250122aca24696edb28715613c656c74ffd",
)
FIELDS = [
    {"path": "environment.python", "operation": "retain parsed major.minor.patch"},
    {
        "path": "environment.platform",
        "operation": "replace exact OS build with Windows",
    },
    {
        "path": "environment.interpreter_sha256",
        "operation": "remove binary fingerprint",
    },
    {
        "path": "blocks[*].record.pid",
        "operation": "remove operating-system process IDs",
    },
]


def canonical(record):
    return (json.dumps(record, indent=2, allow_nan=False) + "\n").encode("utf-8")


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def derive(record, original_identity):
    """Preserve all search values and controls; change only declared public metadata."""
    public = copy.deepcopy(record)
    environment = public["environment"]
    version = re.match(r"^(\d+\.\d+\.\d+)\b", environment["python"])
    if version is None or not environment["platform"].startswith("Windows-"):
        raise ValueError("Expected a reliably parsed Python patch and Windows build")
    environment["python"] = version[1]
    environment["platform"] = "Windows"
    del environment["interpreter_sha256"]
    for item in public["blocks"]:
        block = item["record"]
        del block["pid"]
        item["record_sha256"] = identity(canonical(block))["sha256"]
        item["record_hash_kind"] = "public derivative canonical LF bytes"
    public["publication_derivative"] = {
        "format": "same-forest-public-receipts-v1",
        "original_private_identity": original_identity,
        "changed_fields": FIELDS,
        "nested_hashes": "Public derivative canonical LF bytes, "
        "not original raw blocks",
        "computational_receipts_timers_controls_schedules_changed": False,
    }
    return public


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--complete-private-input", type=Path, required=True)
    parser.add_argument("--failed-private-input", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for path, expected in (
        (args.complete_private_input, COMPLETE),
        (args.failed_private_input, FAILED),
    ):
        name, size, sha256 = expected
        raw = path.read_bytes()
        if identity(raw) != {"bytes": size, "sha256": sha256}:
            raise ValueError("Private original identity differs")
        public = derive(json.loads(raw), identity(raw))
        output = ROOT / "docs" / name
        if output.exists():
            raise FileExistsError("Preserve the existing public derivative")
        encoded = canonical(public)
        output.write_bytes(encoded)
        if path.read_bytes() != raw:
            raise ValueError("Private original changed during derivation")
        rows.append(
            {
                "file": name,
                "public_identity": identity(encoded),
                "private_original_identity": identity(raw),
            }
        )
    manifest = {
        "schema_version": 1,
        "format": "same-forest-public-receipts-v1",
        "changed_fields": FIELDS,
        "private_originals_modified": False,
        "search_rerun": False,
        "attempts": rows,
        "limitations": "The original raw bytes and environment fingerprints "
        "remain private. Public block hashes identify the "
        "derived records. Public data alone cannot verify "
        "the withheld original bytes or machine fingerprints.",
    }
    path = ROOT / "docs/same-forest-repeatability-public-fields.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "attempts": rows,
                "private_originals_modified": False,
                "search_rerun": False,
            }
        )
    )


if __name__ == "__main__":
    main()
