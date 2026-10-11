"""Price a captured input under an explicitly declared finite reference."""

from __future__ import annotations

import hashlib
from pathlib import Path

from game.episode_decision import current_identity
from game.episode_inspection import validate_decision_report
from game.episode_record import (
    RECORD_BYTES,
    _choice,
    _error,
    _number,
    _parse,
    _read,
    canonical,
    integer,
    output_bytes,
)

from . import aggregation_domain
from .report import (
    MODEL,
    THREE_ENEMY_MODEL,
    complete_reference_report,
    qualified_engine_files,
    reference_report_base,
    refused_reference_report,
)

ADAPTIVE_MODEL = "independent_two_round_adaptive_binary53_shaped_v1"
ADAPTIVE_METHOD = "adaptive-physical"


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
    model: str = MODEL,
    method: str = aggregation_domain.PHYSICAL_METHOD,
    max_contributions: int | None = None,
    max_payoff_evaluations: int | None = None,
    max_transitions: int | None = None,
    max_per_action: int | None = None,
    max_work_units: int | None = None,
    state_input: bool = False,
) -> dict:
    """Return a complete report or explicit refusal, with no new search or replay."""
    _choice(model, "model", {MODEL, THREE_ENEMY_MODEL, ADAPTIVE_MODEL})
    if not isinstance(state_input, bool):
        _error("state_input", "require a Boolean input mode")
    if model == ADAPTIVE_MODEL:
        _choice(method, "method", {ADAPTIVE_METHOD})
        if (
            max_paths != 250_000
            or max_total_paths != 1_000_000
            or max_contributions is not None
            or max_payoff_evaluations is not None
        ):
            _error(
                "method controls",
                "adaptive work requires its own transition and work controls",
            )
        return _adaptive_reference(
            path,
            state_input=state_input,
            max_seconds=max_seconds,
            max_transitions=max_transitions,
            max_per_action=max_per_action,
            max_work_units=max_work_units,
        )
    if state_input or any(
        value is not None for value in (max_transitions, max_per_action, max_work_units)
    ):
        _error(
            "method controls",
            "state input and adaptive controls require the two-round adaptive model",
        )
    _choice(
        method,
        "method",
        {aggregation_domain.PHYSICAL_METHOD, aggregation_domain.METHOD},
    )
    _number(
        max_seconds,
        "max_seconds",
        0.000001 if method == aggregation_domain.PHYSICAL_METHOD else 0,
        30.0,
    )
    if max_seconds == 0:
        _error("max_seconds", "require a finite positive deadline")
    integer(max_paths, "max_paths", 1, 250_000)
    integer(max_total_paths, "max_total_paths", 1, 1_000_000)
    if method == aggregation_domain.PHYSICAL_METHOD:
        if max_contributions is not None or max_payoff_evaluations is not None:
            _error(
                "method controls",
                "contribution and payoff controls require sum-convolution",
            )
        limits = {
            "max_paths": integer(max_paths, "max_paths", 1, 250_000),
            "max_total_paths": integer(
                max_total_paths, "max_total_paths", 1, 1_000_000
            ),
            "max_seconds": max_seconds,
        }
        from .one_round import evaluate
    else:
        if max_paths != 250_000 or max_total_paths != 1_000_000:
            _error(
                "method controls",
                "physical leaf controls cannot limit sum-convolution work",
            )
        limits = {
            "max_contributions": integer(
                1_000_000 if max_contributions is None else max_contributions,
                "max_contributions",
                1,
                1_000_000,
            ),
            "max_payoff_evaluations": integer(
                10_000 if max_payoff_evaluations is None else max_payoff_evaluations,
                "max_payoff_evaluations",
                1,
                10_000,
            ),
            "max_seconds": max_seconds,
        }
        from .aggregation import evaluate
    from .one_round import ReferenceLimitExceeded, UnsupportedState

    captured = _read(path, "decision report", RECORD_BYTES)
    decision = validate_decision_report(
        _parse(captured, "decision report", 200_000, 10**300)
    )
    observed = reference_identity()
    base = reference_report_base(
        decision, captured, observed, limits, model=model, computation_method=method
    )
    try:
        if not qualified_engine_files(
            observed["decision_consumer"]["engine_files_sha256"]
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
            evaluation = evaluate(decision["selected_state"], **limits, model=model)
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


def _adaptive_reference(
    path: Path,
    *,
    state_input: bool,
    max_seconds: float,
    max_transitions: int | None,
    max_per_action: int | None,
    max_work_units: int | None,
) -> dict:
    """Share the captured-input boundary across state and saved-decision modes."""
    from game import episode_record as records

    from . import adaptive_report as reports

    limits = {
        "max_transitions": reports.MAX_TRANSITIONS
        if max_transitions is None
        else max_transitions,
        "max_per_action": reports.MAX_PER_ACTION
        if max_per_action is None
        else max_per_action,
        "max_work_units": reports.MAX_WORK_UNITS
        if max_work_units is None
        else max_work_units,
        "max_seconds": max_seconds,
    }
    reports._limits(limits)
    role = "normalized state" if state_input else "decision report"
    captured = _read(path, role, RECORD_BYTES)
    source = _parse(captured, role, 200_000, 10**300)
    if state_input:
        records._state(source, "normalized state")
    else:
        source = validate_decision_report(source)
    observed = reference_identity()
    base = reports.reference_report_base(
        source, captured, observed, limits, state_input=state_input
    )
    try:
        if not qualified_engine_files(
            observed["decision_consumer"]["engine_files_sha256"]
        ):
            report = reports.refused_reference_report(
                base,
                "engine_mismatch",
                "The installed engine differs from the qualified adaptive model. "
                "Install the companion manifest revision before calculating.",
            )
        elif not state_input and source["configuration"]["horizon_rounds"] != 2:
            report = reports.refused_reference_report(
                base,
                "horizon_mismatch",
                "Adaptive pricing requires a saved decision "
                "with exactly two simulated rounds.",
            )
        else:
            try:
                if state_input:
                    reports.qualified_state(base["selected_state"])
                else:
                    reports.qualify_decision(source)
            except records.EpisodeInputError as exc:
                report = reports.refused_reference_report(
                    base, "unsupported_state", str(exc)
                )
            else:
                from .adaptive import (
                    ReferenceArithmeticError,
                    ReferenceCalculationFailed,
                    ReferenceInterrupted,
                    ReferenceLimitExceeded,
                    UnsupportedState,
                    evaluate,
                )

                try:
                    evaluation = evaluate(
                        base["selected_state"],
                        **limits,
                        model=ADAPTIVE_MODEL,
                        horizon=2,
                    )
                except UnsupportedState as exc:
                    report = reports.refused_reference_report(
                        base, "unsupported_state", str(exc)
                    )
                except ReferenceLimitExceeded as exc:
                    report = reports.refused_reference_report(
                        base, "work_limit", str(exc)
                    )
                except ReferenceInterrupted as exc:
                    report = reports.refused_reference_report(
                        base, "interrupted", str(exc)
                    )
                except (ReferenceArithmeticError, ReferenceCalculationFailed) as exc:
                    report = reports.refused_reference_report(
                        base, "runtime_failure", str(exc)
                    )
                else:
                    report = reports.complete_reference_report(base, evaluation)
    except KeyboardInterrupt:
        report = reports.refused_reference_report(
            base, "interrupted", "Adaptive reference calculation interrupted."
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
        report = reports.refused_reference_report(
            base,
            "runtime_failure",
            "Adaptive reference calculation failed: " + str(exc),
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
        report = reports.refused_reference_report(
            base,
            "identity_changed",
            "Producer identity changed during calculation. No value is accepted.",
        )
    output_bytes(report)
    return report
