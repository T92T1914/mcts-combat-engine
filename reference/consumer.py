"""Price a saved decision under the separately declared one-round reference."""

from __future__ import annotations

import hashlib
from pathlib import Path

from game.episode_decision import current_identity
from game.episode_inspection import validate_decision_report
from game.episode_record import (
    RECORD_BYTES,
    _number,
    _parse,
    _read,
    canonical,
    integer,
    output_bytes,
)

from .report import (
    REFERENCE_ENGINE_FILES_SHA256,
    complete_reference_report,
    reference_report_base,
    refused_reference_report,
)


def reference_identity() -> dict:
    """Bind the installed engine, decision helpers and separate reference producer."""
    directory = Path(__file__).resolve().parent
    members = {}
    total = 0
    for path in sorted(directory.glob("*.py")):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("reference identity requires ordinary source files")
        with path.open("rb") as stream:
            data = stream.read(4_194_305)
        total += len(data)
        if len(data) > 4_194_304 or total > 16_777_216 or len(members) >= 16:
            raise RuntimeError("reference identity exceeds source capture limits")
        members["reference/" + path.name] = hashlib.sha256(data).hexdigest()
    entry = directory.parent / "reference_episode.py"
    if entry.is_symlink():
        raise RuntimeError("reference entry identity requires an ordinary file")
    with entry.open("rb") as stream:
        data = stream.read(4_194_305)
    if len(data) > 4_194_304:
        raise RuntimeError("reference entry exceeds source capture limit")
    return {
        "decision_consumer": current_identity(),
        "reference_files_sha256": members,
        "entrypoint_files_sha256": {
            "reference_episode.py": hashlib.sha256(data).hexdigest(),
        },
    }


def reference_decision(
    path: Path,
    *,
    max_paths: int = 250_000,
    max_total_paths: int = 1_000_000,
    max_seconds: float = 30.0,
) -> dict:
    """Return a complete report or explicit refusal, with no new search or replay."""
    from .one_round import ReferenceLimitExceeded, UnsupportedState, evaluate

    _number(max_seconds, "max_seconds", 0.000001, 30.0)
    limits = {
        "max_paths": integer(max_paths, "max_paths", 1, 250_000),
        "max_total_paths": integer(max_total_paths, "max_total_paths", 1, 1_000_000),
        "max_seconds": max_seconds,
    }
    captured = _read(path, "decision report", RECORD_BYTES)
    decision = validate_decision_report(
        _parse(captured, "decision report", 200_000, 10**300)
    )
    observed = reference_identity()
    base = reference_report_base(decision, captured, observed, limits)
    try:
        if (
            observed["decision_consumer"]["engine_files_sha256"]
            != REFERENCE_ENGINE_FILES_SHA256
        ):
            report = refused_reference_report(
                base,
                "engine_mismatch",
                "The installed engine differs from the qualified reference model. "
                "Install the companion manifest revision before calculating.",
            )
        elif decision["configuration"]["horizon_rounds"] != 1:
            report = refused_reference_report(
                base,
                "horizon_mismatch",
                "The saved search uses a different horizon. Obtain a horizon-one "
                "decision or extract a horizon-one stability cell first.",
            )
        else:
            evaluation = evaluate(decision["selected_state"], **limits)
            report = complete_reference_report(base, evaluation)
    except UnsupportedState as exc:
        report = refused_reference_report(base, "unsupported_state", str(exc))
    except ReferenceLimitExceeded as exc:
        report = refused_reference_report(base, "work_limit", str(exc))
    except KeyboardInterrupt:
        report = refused_reference_report(
            base, "interrupted", "Reference calculation interrupted."
        )
    except (
        RuntimeError,
        OSError,
        ValueError,
        TypeError,
        ArithmeticError,
        KeyError,
        AttributeError,
        RecursionError,
        MemoryError,
    ) as exc:
        report = refused_reference_report(
            base, "runtime_failure", "Reference calculation failed: " + str(exc)
        )
    try:
        unchanged = canonical(reference_identity()) == canonical(observed)
    except (
        RuntimeError,
        OSError,
        ValueError,
        TypeError,
        ArithmeticError,
        RecursionError,
        MemoryError,
    ):
        unchanged = False
    if not unchanged:
        report = refused_reference_report(
            base,
            "identity_changed",
            "Producer identity changed during calculation. No value is accepted.",
        )
    output_bytes(report)
    return report
