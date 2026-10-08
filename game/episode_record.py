"""Bounded episode records and environment replay for the checkout example.

Stored states are comparison data. Replay rebuilds content through the existing
loader and returns recorded legal actions through the unchanged game runner.
"""
from __future__ import annotations

import hashlib
import json
import math
import platform
import random
import re
import struct
import sys
import tempfile
from dataclasses import fields
from pathlib import Path
from typing import Any, NoReturn

from engine import Action, Card, CardType, Charm, Combatant, DoT, Element, GameState
from engine.actions import is_legal_action, legal_actions
from game.decision_report import implementation_identity, load_snapshot, normalized
from game.loader import DATA_DIR, RULE_REGISTRY
from game.runner import play_game

CONTENT_BYTES = 262_144
RECORD_BYTES = 8_388_608
MAX_ROUNDS = 30
MAX_SIMS = 64
MAX_HORIZON = 8
SEED_MIN = -(2**63)
SEED_MAX = 2**63 - 1
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CARD_SOURCE = {
    "name", "element", "type", "pip_cost", "accuracy", "damage_min",
    "damage_max", "heal", "dot_tick", "dot_rounds", "modifier", "hits_all",
}
_COMBATANT_SOURCE = {
    "name", "element", "hp", "power_pip_chance", "resist", "boost",
    "is_boss", "attack", "rules",
}


class EpisodeInputError(ValueError):
    """Invalid caller arguments, content or record before environment work."""


class EpisodeRuntimeError(RuntimeError):
    """Admitted recording/replay cannot produce a successful complete output."""


class _Mismatch(Exception):
    def __init__(self, reason: str, location: str, index: int | None = None):
        self.reason = reason
        self.location = location
        self.index = index


def canonical(value: Any) -> bytes:
    """Exact JSON comparison and checkpoint representation, without a newline."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("ascii")


def output_bytes(value: dict) -> bytes:
    try:
        data = canonical(value) + b"\n"
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise EpisodeRuntimeError("output cannot be serialized as finite JSON") from exc
    if len(data) > RECORD_BYTES:
        raise EpisodeRuntimeError("generated output exceeds 8388608 bytes")
    return data


def _error(location: str, message: str) -> NoReturn:
    raise EpisodeInputError(f"{location}: {message}")


def _object(value: Any, location: str, required: set[str],
            optional: set[str] | None = None) -> dict:
    if not isinstance(value, dict):
        _error(location, "must be an object")
    keys = set(value)
    if required - keys or keys - required - (optional or set()):
        _error(location, "missing or unsupported fields")
    return value


def _array(value: Any, location: str, low: int, high: int) -> list:
    if not isinstance(value, list) or not low <= len(value) <= high:
        _error(location, f"must be an array with {low}..{high} entries")
    return value


def _string(value: Any, location: str, low: int = 1, high: int = 128) -> str:
    if not isinstance(value, str) or not low <= len(value) <= high:
        _error(location, f"must be a string with {low}..{high} characters")
    return value


def integer(value: Any, location: str, low: int, high: int) -> int:
    if (isinstance(value, bool) or not isinstance(value, int)
            or not low <= value <= high):
        _error(location, f"must be an integer in {low}..{high}")
    return value


def _number(value: Any, location: str, low: float, high: float) -> None:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not low <= value <= high or not math.isfinite(value)):
        _error(location, f"must be a finite number in {low}..{high}")


def _boolean(value: Any, location: str) -> None:
    if not isinstance(value, bool):
        _error(location, "must be a boolean")


def _choice(value: Any, location: str, choices: set[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        _error(location, "unsupported string value")
    return value


def _digest(value: Any, location: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _error(location, "must be a lowercase SHA-256 digest")


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise EpisodeInputError("duplicate JSON object key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise EpisodeInputError(f"nonfinite JSON number {value!r}")


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        _constant(value)
    return result


def _envelope(value: Any, limit: int, magnitude: int) -> None:
    count = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal count
        count += 1
        if count > limit:
            _error("JSON", f"exceeds {limit} values")
        if isinstance(item, (dict, list)):
            depth += 1
            if depth > 16:
                _error("JSON", "exceeds 16 container levels")
            if isinstance(item, dict):
                for key, child in item.items():
                    _string(key, "JSON key", high=240)
                    visit(child, depth)
            else:
                for child in item:
                    visit(child, depth)
        elif isinstance(item, str):
            _string(item, "JSON string", low=0, high=2048)
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            _number(item, "JSON number", -magnitude, magnitude)

    visit(value, 0)


def _read(path: Path, role: str, limit: int) -> bytes:
    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as exc:
        message = f"{role}: could not read input ({exc.strerror})"
        raise EpisodeInputError(message) from exc
    if len(data) > limit:
        _error(role, f"exceeds {limit} bytes")
    return data


def _parse(data: bytes, role: str, values: int, magnitude: int) -> Any:
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                            parse_constant=_constant, parse_float=_float)
        _envelope(result, values, magnitude)
        return result
    except (UnicodeError, ValueError, OverflowError, RecursionError) as exc:
        raise EpisodeInputError(f"{role}: invalid bounded UTF-8 JSON ({exc})") from exc


def _source_card(value: Any, location: str) -> None:
    obj = _object(value, location, {"name", "element", "type"},
                  _CARD_SOURCE - {"name", "element", "type"})
    for name in ("name", "element", "type"):
        _string(obj[name], f"{location}/{name}")
    for name in ("pip_cost", "damage_min", "damage_max", "heal", "dot_tick"):
        if name in obj:
            integer(obj[name], f"{location}/{name}", 0, 1_000_000)
    if "dot_rounds" in obj:
        integer(obj["dot_rounds"], f"{location}/dot_rounds", 0, 30)
    for name in ("accuracy", "modifier"):
        if name in obj:
            _number(obj[name], f"{location}/{name}", -1_000_000, 1_000_000)
    if "hits_all" in obj:
        _boolean(obj["hits_all"], f"{location}/hits_all")


def _resist(value: Any, location: str) -> None:
    if not isinstance(value, dict) or len(value) > len(Element):
        _error(location, "must be an element mapping")
    for key, number in value.items():
        _choice(key, location, {element.value for element in Element})
        _number(number, location, -1, 1)


def _source_combatant(value: Any, location: str) -> int:
    obj = _object(value, location, {"name", "element", "hp"},
                  _COMBATANT_SOURCE - {"name", "element", "hp"})
    _string(obj["name"], f"{location}/name")
    _string(obj["element"], f"{location}/element")
    integer(obj["hp"], f"{location}/hp", 1, 1_000_000)
    if "power_pip_chance" in obj:
        _number(obj["power_pip_chance"], location, 0, 1)
    if "is_boss" in obj:
        _boolean(obj["is_boss"], location)
    for name in ("resist", "boost"):
        if name in obj:
            _resist(obj[name], f"{location}/{name}")
    if "attack" in obj:
        _source_card(obj["attack"], f"{location}/attack")
    rules = _array(obj.get("rules", []), f"{location}/rules", 0, 2)
    for rule in rules:
        if not isinstance(rule, dict):
            _error(location, "rule must be an object")
        kind = _choice(rule.get("type"), location, set(RULE_REGISTRY))
        parameters = set(RULE_REGISTRY[kind][1])
        _object(rule, location, {"type"}, parameters)
        if "damage" in rule:
            integer(rule["damage"], location, 1, 1_000_000)
        if "blade" in rule:
            _number(rule["blade"], location, 0, 2)
    return len(rules)


def _content_shape(cards: Any, scenarios: Any) -> None:
    cards = _object(cards, "cards", {"cards"})
    for index, card in enumerate(_array(cards["cards"], "cards", 1, 128)):
        _source_card(card, f"cards/{index}")
    scenarios = _object(scenarios, "scenarios", {"scenarios"})["scenarios"]
    if not isinstance(scenarios, dict) or not 1 <= len(scenarios) <= 16:
        _error("scenarios", "must contain 1..16 scenarios")
    for name, value in scenarios.items():
        _string(name, "scenario name")
        obj = _object(value, "scenario", {"player", "deck", "enemies"},
                      {"description"})
        if "description" in obj:
            _string(obj["description"], "description", low=0, high=2048)
        _source_combatant(obj["player"], "player")
        for card_name in _array(obj["deck"], "deck", 1, 128):
            _string(card_name, "deck entry")
        count = sum(_source_combatant(enemy, "enemy")
                    for enemy in _array(obj["enemies"], "enemies", 1, 8))
        if count > 2:
            _error("scenario rules", "at most two across all enemies")


def load_content(cards_path: Path | None = None,
                 scenarios_path: Path | None = None) -> tuple[dict, dict]:
    """Bound original reads once, then reuse the accepted captured-byte loader."""
    if (cards_path is None) != (scenarios_path is None):
        _error("content", "cards and scenarios must be supplied together")
    captured = {
        "cards": _read(cards_path or DATA_DIR / "cards.json", "cards", CONTENT_BYTES),
        "scenarios": _read(scenarios_path or DATA_DIR / "scenarios.json",
                           "scenarios", CONTENT_BYTES),
    }
    _content_shape(*(_parse(captured[role], role, 20_000, 1_000_000)
                     for role in ("cards", "scenarios")))
    try:
        with tempfile.TemporaryDirectory(prefix="mcts-episode-content-") as directory:
            staged = Path(directory)
            for role, data in captured.items():
                (staged / f"{role}.json").write_bytes(data)
            scenarios, identity = load_snapshot(staged / "cards.json",
                                                staged / "scenarios.json")
    except (ValueError, KeyError, TypeError, AttributeError, OSError,
            OverflowError) as exc:
        raise EpisodeInputError(f"content: {exc}") from exc
    identity["kind"] = "built-in" if cards_path is None else "custom"
    return scenarios, identity


def observed_identity() -> dict:
    identity = implementation_identity()
    entry = Path(__file__).resolve().parent.parent / "episode.py"
    identity.update({
        "entrypoint_files_sha256": {"episode.py": hashlib.sha256(
            entry.read_bytes()).hexdigest()},
        "machine": platform.machine(),
        "pointer_bits": struct.calcsize("P") * 8,
        "python_full_version": sys.version,
        "python_build": list(platform.python_build()),
        "python_cache_tag": sys.implementation.cache_tag,
        "rng_state_version": random.Random.VERSION,
    })
    return identity


def rng_digest(rng: random.Random) -> str:
    return hashlib.sha256(canonical(normalized(rng.getstate()))).hexdigest()


def _configuration(rounds: Any, sims: Any, horizon: Any, search_seed: Any) -> dict:
    rounds = integer(rounds, "rounds", 1, MAX_ROUNDS)
    sims = integer(sims, "sims", 1, MAX_SIMS)
    horizon = integer(horizon, "horizon", 1, MAX_HORIZON)
    search_seed = integer(search_seed, "search seed", SEED_MIN, SEED_MAX)
    return {
        "method": "mcts", "mode": "serial_clockless", "search_seed": search_seed,
        "search_rng_mode": "seed_once_continue", "max_rounds": rounds,
        "max_sims_per_decision": sims, "horizon_rounds": horizon,
        "max_transitions_per_decision": sims * horizon, "exploration": 1.2,
        "time_budget_ms": None, "parallel": False, "workers": None,
        "priors": None,
        "policy_rng": {"scheme": "policy-v1", "seed": 0, "used_by_policy": False},
    }


def _record_owner(config: dict):
    # Only recording reaches this import/factory. Replay has no policy factory.
    from engine import mcts_decider
    return mcts_decider(parallel=False, budget_ms=None,
                        seed=config["search_seed"],
                        max_sims=config["max_sims_per_decision"],
                        horizon=config["horizon_rounds"],
                        max_transitions=config["max_transitions_per_decision"])


def _equal(left: Any, right: Any) -> bool:
    return canonical(left) == canonical(right)


def first_difference(left: Any, right: Any, location: str) -> str | None:
    """Find the first canonical difference in sorted objects and ordered lists."""
    visited = 0

    def visit(expected: Any, observed: Any, path: str, depth: int) -> str | None:
        nonlocal visited
        visited += 1
        if visited > 200_000 or depth > 16:
            raise EpisodeRuntimeError("comparison exceeds schema traversal limits")
        if _equal(expected, observed):
            return None
        if isinstance(expected, dict) and isinstance(observed, dict):
            for key in sorted(set(expected) | set(observed)):
                escaped = key.replace("~", "~0").replace("/", "~1")
                child = f"{path}/{escaped}"
                if key not in expected or key not in observed:
                    return child
                difference = visit(expected[key], observed[key], child, depth + 1)
                if difference is not None:
                    return difference
        elif isinstance(expected, list) and isinstance(observed, list):
            for index in range(min(len(expected), len(observed))):
                difference = visit(expected[index], observed[index],
                                   f"{path}/{index}", depth + 1)
                if difference is not None:
                    return difference
            return f"{path}/{min(len(expected), len(observed))}"
        return path

    return visit(left, right, location, 0)


def _final(state: GameState, score: float, rounds: int) -> dict:
    result = state.result()
    return {"state": normalized(state), "score": score,
            "terminal_result": result, "rounds": rounds,
            "termination": "terminal" if result is not None else "round_limit"}


def record_episode(scenario: str = "boss", *, cards_path: Path | None = None,
                   scenarios_path: Path | None = None, environment_seed: int = 7,
                   search_seed: int = 7, rounds: int = 30, sims: int = 16,
                   horizon: int = 4) -> dict:
    config = _configuration(rounds, sims, horizon, search_seed)
    integer(environment_seed, "environment seed", SEED_MIN, SEED_MAX)
    _string(scenario, "scenario name")
    scenarios, content = load_content(cards_path, scenarios_path)
    if scenario not in scenarios:
        _error("scenario", "unknown scenario name")
    implementation = observed_identity()
    if implementation["rng_state_version"] != 3:
        raise EpisodeRuntimeError("unsupported environment RNG state version")
    rng = random.Random(environment_seed)
    state, deck = scenarios[scenario](rng)
    initial = normalized(state)
    after_scenario = rng_digest(rng)
    steps: list[dict[str, Any]] = []
    with _record_owner(config) as choose:
        def recorder(current: GameState, policy_rng: random.Random) -> Action:
            snapshot = normalized(current)
            action = choose(current, policy_rng)
            if not _equal(snapshot, normalized(current)):
                raise EpisodeRuntimeError(
                    "recording policy mutated the environment state")
            if (not isinstance(action, Action) or not is_legal_action(current, action)
                    or action not in legal_actions(current)):
                raise EpisodeRuntimeError("recording policy returned an illegal action")
            steps.append({"index": len(steps), "round_num": current.round_num,
                          "state": snapshot,
                          "action": {"card_idx": action.card_idx,
                                     "target_idx": action.target_idx,
                                     "label": action.describe(current)}})
            return action

        score = play_game(state, deck, recorder, rng, max_rounds=rounds,
                          policy_rng=random.Random("policy-v1:0"))
    record = {
        "format": "mcts-episode-record", "schema_version": 1, "content": content,
        "scenario": {"name": scenario, "environment_seed": environment_seed,
                     "deck": normalized(deck)},
        "initial_state": initial, "implementation": implementation,
        "configuration": config,
        "environment_rng": {"checkpoint_scheme": "python-random-getstate-json-v1",
                            "state_version": 3,
                            "after_scenario_sha256": after_scenario,
                            "final_sha256": rng_digest(rng)},
        "steps": steps, "final": _final(state, score, len(steps)),
    }
    if not _equal(implementation, observed_identity()):
        raise EpisodeRuntimeError("implementation identity changed during recording")
    try:
        validate_record(record)
    except EpisodeInputError as exc:
        message = f"generated record exceeds its schema: {exc}"
        raise EpisodeRuntimeError(message) from exc
    output_bytes(record)
    return record


def _modeled(value: Any, location: str, cls: type) -> dict:
    return _object(value, location, {field.name for field in fields(cls)})


def _card(value: Any, location: str) -> None:
    obj = _modeled(value, location, Card)
    _string(obj["name"], location)
    _choice(obj["element"], location, {element.value for element in Element})
    _choice(obj["card_type"], location, {kind.value for kind in CardType})
    integer(obj["pip_cost"], location, 0, 14)
    for name in ("damage_min", "damage_max", "heal", "dot_tick"):
        integer(obj[name], location, 0, 1_000_000)
    integer(obj["dot_rounds"], location, 0, 30)
    _number(obj["accuracy"], location, 0, 1)
    if obj["accuracy"] == 0:
        _error(location, "accuracy must be positive")
    _number(obj["modifier"], location, -1_000_000, 1_000_000)
    _boolean(obj["hits_all"], location)


def _rule(value: Any, location: str) -> None:
    obj = _object(value, location, {"type", "parameters", "description"})
    kind = obj["type"]
    _choice(kind, location, set(RULE_REGISTRY))
    parameters = _object(obj["parameters"], location, set(RULE_REGISTRY[kind][1]))
    if kind == "punish_traps":
        integer(parameters["damage"], location, 1, 1_000_000)
    else:
        _number(parameters["blade"], location, 0, 2)
        if parameters["blade"] == 0:
            _error(location, "rule blade must be positive")
    _string(obj["description"], location, high=2048)


def _combatant(value: Any, location: str) -> None:
    obj = _modeled(value, location, Combatant)
    _string(obj["name"], location)
    _choice(obj["element"], location, {element.value for element in Element})
    integer(obj["hp"], location, 0, 1_000_000)
    integer(obj["max_hp"], location, 1, 1_000_000)
    for name in ("pips", "power_pips"):
        integer(obj[name], location, 0, 30)
    _number(obj["power_pip_chance"], location, 0, 1)
    for name in ("resist", "boost"):
        _resist(obj[name], location)
    for name in ("blades", "traps", "shields"):
        for charm in _array(obj[name], location, 0, 128):
            charm = _modeled(charm, location, Charm)
            _number(charm["value"], location, -2, 2)
            _choice(charm["element"], location, {e.value for e in Element})
    for dot in _array(obj["dots"], location, 0, 256):
        dot = _modeled(dot, location, DoT)
        integer(dot["tick"], location, 0, 10**300)
        integer(dot["rounds_left"], location, 0, 30)
        _choice(dot["element"], location, {e.value for e in Element})
    _boolean(obj["is_boss"], location)
    if obj["base_attack"] is not None:
        _card(obj["base_attack"], location)
    if obj["policy"] is not None:
        _error(location, "loader-created policy must be null")


def _state(value: Any, location: str) -> None:
    obj = _modeled(value, location, GameState)
    _combatant(obj["player"], f"{location}/player")
    for enemy in _array(obj["enemies"], location, 1, 8):
        _combatant(enemy, f"{location}/enemies")
    # Final hand can have six cards after the last played action.
    for card in _array(obj["hand"], location, 0, 7):
        _card(card, f"{location}/hand")
    integer(obj["round_num"], location, 1, 31)
    for rule in _array(obj["boss_rules"], location, 0, 2):
        _rule(rule, f"{location}/boss_rules")


def _content_identity(value: Any) -> None:
    obj = _object(value, "content", {"kind", "cards", "scenarios"})
    _choice(obj["kind"], "content/kind", {"built-in", "custom"})
    for role in ("cards", "scenarios"):
        file = _object(obj[role], f"content/{role}", {"bytes", "sha256"})
        integer(file["bytes"], "content bytes", 1, CONTENT_BYTES)
        _digest(file["sha256"], "content digest")


def _hash_map(value: Any, location: str) -> None:
    if not isinstance(value, dict) or not 1 <= len(value) <= 128:
        _error(location, "must contain 1..128 observed file hashes")
    for name, digest in value.items():
        _string(name, location, high=240)
        if (name.startswith("/") or "\\" in name or ":" in name
                or any(part in ("", ".", "..") for part in name.split("/"))):
            _error(location, "file names must be relative comparison names")
        _digest(digest, location)


def _implementation(value: Any) -> None:
    obj = _object(value, "implementation", {
        "python", "python_implementation", "platform", "engine_import_kind",
        "distribution_version", "distribution_matches_import",
        "engine_files_sha256", "example_files_sha256", "entrypoint_files_sha256",
        "machine", "pointer_bits", "python_full_version", "python_build",
        "python_cache_tag", "rng_state_version",
    })
    for name in ("python", "python_implementation", "platform", "machine"):
        _string(obj[name], name)
    _string(obj["python_full_version"], "Python version", high=2048)
    for item in _array(obj["python_build"], "Python build", 2, 2):
        _string(item, "Python build", low=0, high=2048)
    if obj["python_cache_tag"] is not None:
        _string(obj["python_cache_tag"], "Python cache tag")
    integer(obj["pointer_bits"], "pointer width", 32, 64)
    if obj["pointer_bits"] not in (32, 64):
        _error("pointer width", "must be 32 or 64")
    integer(obj["rng_state_version"], "RNG version", 3, 3)
    _choice(obj["engine_import_kind"], "engine import", {"source", "site-packages"})
    if obj["distribution_version"] is not None:
        _string(obj["distribution_version"], "distribution version")
    _boolean(obj["distribution_matches_import"], "distribution match")
    for name in ("engine_files_sha256", "example_files_sha256",
                 "entrypoint_files_sha256"):
        _hash_map(obj[name], name)
    if set(obj["entrypoint_files_sha256"]) != {"episode.py"}:
        _error("entrypoint identity", "must identify episode.py")


def validate_record(value: Any) -> dict:
    """Validate retained data without constructing an environment or policy."""
    _envelope(value, 200_000, 10**300)
    obj = _object(value, "record", {
        "format", "schema_version", "content", "scenario", "initial_state",
        "implementation", "configuration", "environment_rng", "steps", "final",
    })
    _choice(obj["format"], "record format", {"mcts-episode-record"})
    integer(obj["schema_version"], "schema version", 1, 1)
    _content_identity(obj["content"])
    _implementation(obj["implementation"])
    scenario = _object(obj["scenario"], "scenario",
                       {"name", "environment_seed", "deck"})
    _string(scenario["name"], "scenario name")
    integer(scenario["environment_seed"], "environment seed", SEED_MIN, SEED_MAX)
    for card in _array(scenario["deck"], "deck", 1, 128):
        _card(card, "deck card")
    _state(obj["initial_state"], "initial_state")
    if obj["initial_state"]["round_num"] != 1:
        _error("initial_state", "must start at round one")
    config = obj["configuration"]
    if not isinstance(config, dict):
        _error("configuration", "must be an object")
    required = _configuration(
        config.get("max_rounds"), config.get("max_sims_per_decision"),
        config.get("horizon_rounds"), config.get("search_seed"))
    if not _equal(config, required):
        _error("configuration", "unsupported recording policy/configuration")
    rng = _object(obj["environment_rng"], "environment_rng", {
        "checkpoint_scheme", "state_version", "after_scenario_sha256", "final_sha256",
    })
    _choice(rng["checkpoint_scheme"], "RNG scheme", {"python-random-getstate-json-v1"})
    integer(rng["state_version"], "RNG state version", 3, 3)
    for name in ("after_scenario_sha256", "final_sha256"):
        _digest(rng[name], f"environment_rng/{name}")
    steps = _array(obj["steps"], "steps", 0, config["max_rounds"])
    for index, step in enumerate(steps):
        step = _object(step, f"steps/{index}",
                       {"index", "round_num", "state", "action"})
        integer(step["index"], "step index", index, index)
        integer(step["round_num"], "step round", index + 1, index + 1)
        _state(step["state"], f"steps/{index}/state")
        if step["state"]["round_num"] != index + 1:
            _error("step state", "round must agree with step")
        action = _object(step["action"], "action", {"card_idx", "target_idx", "label"})
        for name, high in (("card_idx", 6), ("target_idx", 7)):
            if action[name] is not None:
                integer(action[name], name, 0, high)
        _string(action["label"], "action label", high=260)
    final = _object(obj["final"], "final", {
        "state", "score", "terminal_result", "rounds", "termination",
    })
    _state(final["state"], "final/state")
    integer(final["rounds"], "final rounds", len(steps), len(steps))
    if final["state"]["round_num"] != len(steps) + 1:
        _error("final/state", "round must agree with completed steps")
    _number(final["score"], "score", 0, 1)
    result = final["terminal_result"]
    if result is not None:
        _number(result, "terminal result", 0, 1)
        if result not in (0, 1):
            _error("terminal result", "must be zero, one or null")
    _choice(final["termination"], "termination", {"terminal", "round_limit"})
    if final["termination"] == "terminal":
        if result is None or final["score"] != result:
            _error("final", "terminal result and score must agree")
    elif result is not None or len(steps) != config["max_rounds"]:
        _error("final", "round-limit episode must consume its cap and remain ongoing")
    return obj


def _result(record_identity: dict, status: str) -> dict:
    return {"format": "mcts-episode-replay-result", "schema_version": 1,
            "status": status, "record": record_identity, "search_recomputed": False}


def replay_episode(record_path: Path, *, cards_path: Path | None = None,
                   scenarios_path: Path | None = None) -> tuple[dict, int]:
    data = _read(record_path, "record", RECORD_BYTES)
    record = validate_record(_parse(data, "record", 200_000, 10**300))
    reference = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    scenarios, content = load_content(cards_path, scenarios_path)
    implementation = observed_identity()
    for reason, current in (("content", content), ("implementation", implementation)):
        if not _equal(record[reason], current):
            result = _result(reference, "incompatible")
            result.update({"reason": reason, "location": first_difference(
                record[reason], current, f"/{reason}")})
            return result, 3
    selected = record["scenario"]
    if selected["name"] not in scenarios:
        _error("scenario", "unknown scenario name")
    rng = random.Random(selected["environment_seed"])
    state, deck = scenarios[selected["name"]](rng)
    consumed = 0

    def require(left: Any, right: Any, reason: str, location: str,
                index: int | None = None) -> None:
        difference = first_difference(left, right, location)
        if difference is not None:
            raise _Mismatch(reason, difference, index)

    def replay_action(current: GameState, policy_rng: random.Random) -> Action:
        nonlocal consumed
        if consumed == len(record["steps"]):
            raise _Mismatch("missing_step", f"/steps/{consumed}", consumed)
        step = record["steps"][consumed]
        require(step["state"], normalized(current), "boundary_state",
                f"/steps/{consumed}/state", consumed)
        require(step["round_num"], current.round_num, "boundary_state",
                f"/steps/{consumed}/round_num", consumed)
        saved = step["action"]
        action = Action(saved["card_idx"], saved["target_idx"])
        if not is_legal_action(current, action) or action not in legal_actions(current):
            raise _Mismatch("illegal_action", f"/steps/{consumed}/action", consumed)
        require(saved["label"], action.describe(current), "action_label",
                f"/steps/{consumed}/action/label", consumed)
        consumed += 1
        return action

    try:
        require(record["initial_state"], normalized(state),
                "initial_state", "/initial_state")
        require(selected["deck"], normalized(deck), "deck", "/scenario/deck")
        require(record["environment_rng"]["after_scenario_sha256"], rng_digest(rng),
                "rng_checkpoint", "/environment_rng/after_scenario_sha256")
        score = play_game(state, deck, replay_action, rng,
                          max_rounds=record["configuration"]["max_rounds"],
                          policy_rng=random.Random("policy-v1:0"))
        if consumed != len(record["steps"]):
            raise _Mismatch("extra_step", f"/steps/{consumed}", consumed)
        final = _final(state, score, consumed)
        require(record["final"], final, "final", "/final")
        require(record["environment_rng"]["final_sha256"], rng_digest(rng),
                "rng_checkpoint", "/environment_rng/final_sha256")
    except _Mismatch as exc:
        result = _result(reference, "mismatch")
        result.update({"reason": exc.reason, "location": exc.location})
        if exc.index is not None:
            result["step_index"] = exc.index
        return result, 1
    if not _equal(implementation, observed_identity()):
        raise EpisodeRuntimeError("implementation identity changed during replay")
    result = _result(reference, "environment_replay_verified")
    result.update({"content": content,
                   "scenario": {"name": selected["name"],
                                "environment_seed": selected["environment_seed"]},
                   "implementation": implementation, "verified_steps": consumed,
                   "final": final})
    output_bytes(result)
    return result, 0
