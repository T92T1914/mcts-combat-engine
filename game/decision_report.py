"""Input snapshots and decision reports for the checkout demo.

The engine wheel has no content loader or command-line entry point. This
example layer records one decision made by its existing engine and policy.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import sysconfig
import tempfile
from dataclasses import fields, is_dataclass
from enum import Enum
from importlib import metadata
from pathlib import Path
from typing import Any

import engine
from engine import Action, Card, GameState, legal_actions

from .loader import DATA_DIR, RULE_REGISTRY, load_cards, load_scenarios


def _object(value: Any, context: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _array(value: Any, context: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    return value


def _finite_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON number {value!r} is unsupported")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        _finite_constant(value)
    return parsed


def _json_bytes(data: bytes, role: str) -> dict:
    try:
        # Decode explicitly: these are the UTF-8 bytes the existing loader reads.
        raw = json.loads(
            data.decode("utf-8"),
            parse_constant=_finite_constant,
            parse_float=_finite_float,
        )
    except (UnicodeError, ValueError) as exc:
        raise ValueError(f"{role}: invalid UTF-8 JSON: {exc}") from exc
    return _object(raw, role)


def _combatant_shape(value: Any, context: str) -> None:
    obj = _object(value, context)
    for field in ("name", "element"):
        if field in obj and not isinstance(obj[field], str):
            raise ValueError(f"{context} {field} must be a string")
    for field in ("resist", "boost"):
        if field in obj:
            _object(obj[field], f"{context} {field}")
    if "attack" in obj:
        _object(obj["attack"], f"{context} attack")
    if "rules" in obj:
        for index, rule in enumerate(_array(obj["rules"], f"{context} rules")):
            rule = _object(rule, f"{context} rule {index}")
            if "type" in rule and not isinstance(rule["type"], str):
                raise ValueError(f"{context} rule {index} type must be a string")


def _content_shape(cards: dict, scenarios: dict) -> None:
    for index, card in enumerate(_array(cards.get("cards"), "cards.json cards")):
        _object(card, f"cards.json card {index}")
    collection = _object(scenarios.get("scenarios"), "scenarios.json scenarios")
    for name, spec in collection.items():
        context = f"scenarios.json scenario {name!r}"
        spec = _object(spec, context)
        # Missing required fields are left to the existing contextual validator.
        if "player" in spec:
            _combatant_shape(spec["player"], f"{context} player")
        if "enemies" in spec:
            for index, enemy in enumerate(
                _array(spec["enemies"], f"{context} enemies")
            ):
                _combatant_shape(enemy, f"{context} enemy {index}")
        if "deck" in spec:
            for card in _array(spec["deck"], f"{context} deck"):
                if not isinstance(card, str):
                    raise ValueError(
                        f"{context} deck entries must be card name strings"
                    )


def load_snapshot(
    cards_path: Path | None = None, scenarios_path: Path | None = None
) -> tuple[dict, dict]:
    """Load captured bytes through the existing loaders, without a reread race."""
    custom = cards_path is not None
    paths = {
        "cards": cards_path or DATA_DIR / "cards.json",
        "scenarios": scenarios_path or DATA_DIR / "scenarios.json",
    }
    captured = {}
    for role, path in paths.items():
        try:
            captured[role] = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"{role} input could not be read: {exc.strerror}") from exc
    _content_shape(
        _json_bytes(captured["cards"], "cards.json"),
        _json_bytes(captured["scenarios"], "scenarios.json"),
    )
    # The loaders only see these copies. A caller changing either original after
    # capture cannot make the report's digest describe different parsed bytes.
    with tempfile.TemporaryDirectory(prefix="mcts-content-") as directory:
        staged = Path(directory)
        for role, data in captured.items():
            (staged / f"{role}.json").write_bytes(data)
        cards = load_cards(staged / "cards.json")
        scenarios = load_scenarios(staged / "scenarios.json", cards)
    identity = {
        role: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for role, data in captured.items()
    }
    return scenarios, {"kind": "custom" if custom else "built-in", **identity}


def normalized(value: Any) -> Any:
    """Preserve complete modeled fields, including effective registered rules."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: normalized(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {normalized(key): normalized(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalized(item) for item in value]
    for name, (cls, parameters) in RULE_REGISTRY.items():
        if type(value) is cls:
            return {
                "type": name,
                "parameters": {
                    name: normalized(getattr(value, name)) for name in parameters
                },
                "description": value.description,
            }
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise ValueError(f"unsupported modeled report type: {type(value).__name__}")


def _file_hashes(directory: Path) -> dict[str, str]:
    paths = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and (path.suffix in (".py", ".pyd", ".so") or path.name == "py.typed")
    )
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths
    }


def implementation_identity() -> dict:
    engine_dir = Path(engine.__file__).resolve().parent
    example_dir = Path(__file__).resolve().parent
    distribution_version = None
    distribution_matches_import = False
    try:
        distribution = metadata.distribution("mcts-combat-engine")
        distribution_version = distribution.version
        distribution_matches_import = (
            Path(str(distribution.locate_file("engine"))).resolve() == engine_dir
        )
    except metadata.PackageNotFoundError:
        pass
    site_directories = {
        Path(sysconfig.get_path(name)).resolve() for name in ("purelib", "platlib")
    }
    installed = any(
        engine_dir.is_relative_to(directory) for directory in site_directories
    )
    demo_path = example_dir.parent / "demo.py"
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.system(),
        "engine_import_kind": "site-packages" if installed else "source",
        "distribution_version": distribution_version,
        "distribution_matches_import": distribution_matches_import,
        "engine_files_sha256": _file_hashes(engine_dir),
        "example_files_sha256": {
            "demo.py": hashlib.sha256(demo_path.read_bytes()).hexdigest(),
            **{
                f"game/{path}": digest
                for path, digest in _file_hashes(example_dir).items()
            },
        },
    }


def report_base(
    state: GameState, deck: list[Card], content: dict, scenario: str, scenario_seed: int
) -> dict:
    return {
        "format": "mcts-decision-report",
        "schema_version": 1,
        "content": content,
        "scenario": {"name": scenario, "seed": scenario_seed, "deck": normalized(deck)},
        "initial_state": normalized(state),
        "implementation": implementation_identity(),
        "value_semantics": "MCTS terminal wins score 1 - 0.045 * min(6, depth); "
        "terminal losses score 0.15 * min(depth, h) / h, where "
        "h = max(1, horizon_rounds). One-round terminal wins score 1 and losses 0. "
        "Ongoing horizon states use the existing HP/setup heuristic. "
        "Means are shaped simulator rewards, not calibrated win probabilities. "
        "One-round samples are not MCTS visits.",
    }


def finish_report(
    base: dict,
    state: GameState,
    configuration: dict,
    work: dict,
    statistics: list[tuple[Action, int, float]],
    ranking: list[Action],
    elapsed: float,
) -> dict:
    by_action = {action: (count, value_sum) for action, count, value_sum in statistics}
    count_name = "visits" if configuration["method"] == "mcts" else "samples"

    def identity(action: Action) -> dict:
        return {"card_idx": action.card_idx, "target_idx": action.target_idx}

    choices = []
    for action in legal_actions(state):
        count, value_sum = by_action.get(action, (0, 0.0))
        choices.append(
            {
                **identity(action),
                "label": action.describe(state),
                "status": "sampled" if count else "unvisited",
                count_name: count,
                "value_sum": value_sum,
                "mean_shaped_reward": value_sum / count if count else None,
            }
        )
    return {
        **base,
        "configuration": configuration,
        "work": work,
        "elapsed_seconds": elapsed,
        "legal_actions": choices,
        "ranking": [identity(action) for action in ranking],
        "recommendation": (
            {**identity(ranking[0]), "label": ranking[0].describe(state)}
            if ranking
            else None
        ),
    }
