"""One fresh fixed-work decision from a validated saved pre-action state."""
from __future__ import annotations

import hashlib
import math
import platform
import random
import struct
import sys
import sysconfig
import time
from dataclasses import fields
from importlib import metadata
from pathlib import Path
from typing import Any, NoReturn

import engine
from engine import (
    MCTS,
    Action,
    Card,
    CardType,
    Charm,
    Combatant,
    DoT,
    Element,
    GameState,
    RankedAction,
    legal_actions,
)
from engine.actions import is_legal_action
from engine.rules import EnrageBelowHalf, PunishTraps

from .decision_report import finish_report, normalized
from .episode_record import (
    RECORD_BYTES,
    SEED_MAX,
    SEED_MIN,
    EpisodeInputError,
    EpisodeRuntimeError,
    _parse,
    _read,
    canonical,
    integer,
    output_bytes,
    validate_record,
)
from .loader import RULE_REGISTRY, parse_card

IDENTITY_FILES = 128
IDENTITY_FILE_BYTES = 4_194_304
IDENTITY_TOTAL_BYTES = 16_777_216
VALUE_SEMANTICS = (
    "MCTS terminal wins score 1 - 0.045 * min(6, depth); "
    "terminal losses score 0.15 * min(depth, h) / h, where "
    "h = max(1, horizon_rounds). One-round terminal wins score 1 and losses 0. "
    "Ongoing horizon states use the existing HP/setup heuristic. "
    "Means are shaped simulator rewards, not calibrated win probabilities. "
    "One-round samples are not MCTS visits."
)
_FIELDS: dict[type, set[str]] = {
    Card: {"name", "element", "card_type", "pip_cost", "accuracy", "damage_min",
           "damage_max", "heal", "dot_tick", "dot_rounds", "modifier", "hits_all"},
    Charm: {"value", "element"},
    DoT: {"tick", "rounds_left", "element"},
    Combatant: {"name", "element", "hp", "max_hp", "pips", "power_pips",
                "power_pip_chance", "resist", "boost", "blades", "traps",
                "shields", "dots", "is_boss", "base_attack", "policy"},
    GameState: {"player", "enemies", "hand", "round_num", "boss_rules"},
}
_RUNTIME_FIELDS = (
    "python", "python_implementation", "platform", "engine_import_kind",
    "distribution_version", "distribution_matches_import", "machine",
    "pointer_bits", "python_full_version", "python_build", "python_cache_tag",
    "rng_state_version",
)


class DecisionRuntimeError(EpisodeRuntimeError):
    """Admitted state cannot yield a complete, stable current decision report."""


def _input(location: str, message: str) -> NoReturn:
    raise EpisodeInputError(f"{location}: {message}")


def _model_shape(location: str) -> None:
    for cls, expected in _FIELDS.items():
        if {field.name for field in fields(cls)} != expected:
            _input(location, f"unsupported current {cls.__name__} fields")
    if ({item.value for item in Element} != {
            "ember", "frost", "gale", "rune", "verdant", "shade", "aether",
            "neutral"} or {item.value for item in CardType} != {
            "damage", "heal", "blade", "trap", "shield", "utility"}):
        _input(location, "unsupported current enums")
    expected_rules: dict[str, tuple[type, set[str]]] = {
        "punish_traps": (PunishTraps, {"damage"}),
        "enrage_below_half": (EnrageBelowHalf, {"blade"}),
    }
    if set(RULE_REGISTRY) != set(expected_rules):
        _input(location, "unsupported current rule registry")
    for kind, (cls, parameters) in expected_rules.items():
        current_cls, current_parameters = RULE_REGISTRY[kind]
        if current_cls is not cls or set(current_parameters) != parameters:
            _input(location, f"unsupported current rule {kind}")


def _card(value: dict, location: str) -> Card:
    source = dict(value)
    source["type"] = source.pop("card_type")
    try:
        return parse_card(source, location)
    except (ValueError, TypeError, ArithmeticError) as exc:
        _input(location, f"current card validation failed ({exc})")


def _combatant(value: dict, location: str) -> Combatant:
    if value["hp"] > value["max_hp"]:
        _input(f"{location}/hp", "must not exceed max_hp")
    if value["pips"] + value["power_pips"] > 7:
        _input(location, "pips plus power_pips must not exceed seven slots")
    attack = value["base_attack"]
    if attack is not None:
        attack = _card(attack, f"{location}/base_attack")
        if attack.card_type is not CardType.DAMAGE:
            _input(f"{location}/base_attack", "must be a damage card")
    dots = []
    for index, dot in enumerate(value["dots"]):
        if dot["rounds_left"] <= 0:
            _input(f"{location}/dots/{index}/rounds_left", "must be positive")
        dots.append(DoT(dot["tick"], dot["rounds_left"], Element(dot["element"])))
    modifiers = {
        name: [Charm(charm["value"], Element(charm["element"]))
               for charm in value[name]]
        for name in ("blades", "traps", "shields")
    }
    return Combatant(
        name=value["name"], element=Element(value["element"]), hp=value["hp"],
        max_hp=value["max_hp"], pips=value["pips"], power_pips=value["power_pips"],
        power_pip_chance=value["power_pip_chance"],
        resist={Element(key): item for key, item in value["resist"].items()},
        boost={Element(key): item for key, item in value["boost"].items()},
        blades=modifiers["blades"], traps=modifiers["traps"],
        shields=modifiers["shields"], dots=dots, is_boss=value["is_boss"],
        base_attack=attack, policy=None,
    )


def _rule(value: dict, location: str) -> Any:
    cls, parameters = RULE_REGISTRY[value["type"]]
    supplied = value["parameters"]
    if set(supplied) != set(parameters):
        _input(f"{location}/parameters", "unsupported parameter fields")
    for name, (validator, requirement) in parameters.items():
        if not validator(supplied[name]):
            _input(f"{location}/parameters/{name}", f"must be {requirement}")
    rule = cls(**supplied)
    if canonical(normalized(rule)) != canonical(value):
        _input(location, "current registered rule cannot reproduce stored fields")
    return rule


def _reconstruct(value: dict, location: str) -> GameState:
    """Called only after complete live episode-schema admission."""
    _model_shape(location)
    try:
        state = GameState(
            player=_combatant(value["player"], f"{location}/player"),
            enemies=[_combatant(enemy, f"{location}/enemies/{index}")
                     for index, enemy in enumerate(value["enemies"])],
            hand=[_card(card, f"{location}/hand/{index}")
                  for index, card in enumerate(value["hand"])],
            round_num=value["round_num"],
            boss_rules=[_rule(rule, f"{location}/boss_rules/{index}")
                        for index, rule in enumerate(value["boss_rules"])],
        )
        if canonical(normalized(state)) != canonical(value):
            _input(location, "current model cannot preserve complete stored fields")
    except EpisodeInputError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError) as exc:
        _input(location, f"current model construction failed ({exc})")
    return state


def current_identity() -> dict:
    """Observe imported engine, complete adjacent helpers and this consumer entry."""
    engine_dir = Path(engine.__file__).resolve().parent
    example_dir = Path(__file__).resolve().parent
    observed_files = 0
    observed_bytes = 0

    def digest(path: Path) -> str:
        nonlocal observed_files, observed_bytes
        observed_files += 1
        if observed_files > IDENTITY_FILES:
            raise DecisionRuntimeError("identity exceeds 128 observed files")
        with path.open("rb") as stream:
            data = stream.read(IDENTITY_FILE_BYTES + 1)
        if len(data) > IDENTITY_FILE_BYTES:
            raise DecisionRuntimeError("identity member exceeds 4194304 bytes")
        observed_bytes += len(data)
        if observed_bytes > IDENTITY_TOTAL_BYTES:
            raise DecisionRuntimeError("identity exceeds 16777216 total bytes")
        return hashlib.sha256(data).hexdigest()

    def members(directory: Path, prefix: str = "") -> dict[str, str]:
        observed = {}
        for path in sorted(directory.rglob("*")):
            if ("__pycache__" not in path.parts and path.is_file()
                    and (path.suffix in (".py", ".pyd", ".so")
                         or path.name == "py.typed")):
                observed[prefix + path.relative_to(directory).as_posix()] = digest(path)
        if not observed:
            raise DecisionRuntimeError("identity source directory has no members")
        return observed

    try:
        engine_members = members(engine_dir)
        example_members = members(example_dir, "game/")
        entry_members = {"decide_episode.py": digest(example_dir.parent /
                                                   "decide_episode.py")}
        distribution_version = None
        distribution_matches_import = False
        try:
            distribution = metadata.distribution("mcts-combat-engine")
            distribution_version = distribution.version
            distribution_matches_import = (
                Path(str(distribution.locate_file("engine"))).resolve() == engine_dir)
        except metadata.PackageNotFoundError:
            pass
        sites = {Path(sysconfig.get_path(name)).resolve()
                 for name in ("purelib", "platlib")}
        return {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.system(),
            "engine_import_kind": ("site-packages" if any(
                engine_dir.is_relative_to(site) for site in sites) else "source"),
            "distribution_version": distribution_version,
            "distribution_matches_import": distribution_matches_import,
            "engine_files_sha256": engine_members,
            "example_files_sha256": example_members,
            "entrypoint_files_sha256": entry_members,
            "machine": platform.machine(), "pointer_bits": struct.calcsize("P") * 8,
            "python_full_version": sys.version,
            "python_build": list(platform.python_build()),
            "python_cache_tag": sys.implementation.cache_tag,
            "rng_state_version": random.Random.VERSION,
        }
    except (OSError, ValueError, TypeError, ArithmeticError) as exc:
        message = f"current identity observation failed ({exc})"
        raise DecisionRuntimeError(message) from exc


def _action(action: Action, state: GameState, legal: set[Action]) -> None:
    if not isinstance(action, Action) or not is_legal_action(state, action):
        raise DecisionRuntimeError("search reported an invalid action identity")
    if action not in legal:
        raise DecisionRuntimeError("search reported an action outside current choices")


def _statistics(search: MCTS, ranked: list[RankedAction], state: GameState,
                sims: int, horizon: int) -> tuple[list, list[Action], dict]:
    legal = set(legal_actions(state))
    statistics = search.last_root_statistics
    by_action = {}
    for action, visits, value_sum in statistics:
        _action(action, state, legal)
        if action in by_action:
            raise DecisionRuntimeError("search reported duplicate root statistics")
        if (isinstance(visits, bool) or not isinstance(visits, int) or visits < 0
                or isinstance(value_sum, bool)
                or not isinstance(value_sum, (int, float))
                or not math.isfinite(value_sum)
                or (not visits and value_sum != 0)
                or (visits and not math.isfinite(value_sum / visits))):
            raise DecisionRuntimeError("search reported invalid raw root statistics")
        by_action[action] = (visits, value_sum)
    ranking = []
    for row in ranked:
        _action(row.action, state, legal)
        if row.action in ranking or row.action not in by_action:
            raise DecisionRuntimeError("search reported inconsistent ranking")
        visits, value_sum = by_action[row.action]
        if (not visits or isinstance(row.visits, bool)
                or not isinstance(row.visits, int) or row.visits != visits
                or isinstance(row.win_rate, bool) or not math.isfinite(row.win_rate)
                or row.win_rate != value_sum / visits
                or row.label != row.action.describe(state)):
            raise DecisionRuntimeError("search ranking disagrees with raw statistics")
        ranking.append(row.action)
    if set(ranking) != {action for action, (visits, _) in by_action.items() if visits}:
        raise DecisionRuntimeError("search omitted sampled ranking alternatives")
    counts = (search.last_sims, search.last_transitions, search.last_unused_transitions)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in counts):
        raise DecisionRuntimeError("search reported invalid work counts")
    if (search.last_sims != sims or sum(row[1] for row in statistics) != sims
            or not 0 <= search.last_transitions <= sims * horizon
            or search.last_unused_transitions != (
                sims * horizon - search.last_transitions)
            or not isinstance(search.last_stop_reasons, tuple)
            or any(reason not in {"simulation_cap", "transition_allowance"}
                   for reason in search.last_stop_reasons)):
        raise DecisionRuntimeError("search reported inconsistent fixed work")
    return statistics, ranking, {
        "simulations": search.last_sims, "transitions": search.last_transitions,
        "unused_transitions": search.last_unused_transitions,
        "stop_reasons": list(search.last_stop_reasons),
    }


def _decision_from_record(data: bytes, record: dict, *, step: int, seed: int,
                          sims: int, horizon: int, exploration: float | None,
                          final_action_rule: str | None,
                          implementation: dict | None = None) -> dict:
    """Use one already captured/admitted episode, never rereading its path."""
    from .episode_inspection import decision_ranking, validate_decision_report

    version = 2 if exploration is not None or final_action_rule is not None else 1
    coefficient = 1.2 if exploration is None else exploration
    rule = "mean_visits" if final_action_rule is None else final_action_rule
    pointer = f"/steps/{step}/state"
    if step >= len(record["steps"]):
        _input(f"/steps/{step}", "selected step does not exist")
    selected = record["steps"][step]
    saved_state = canonical(selected["state"])
    state = _reconstruct(selected["state"], pointer)
    if state.is_terminal():
        _input(pointer, "terminal state has no decision remaining")
    try:
        observed = current_identity()
        if (implementation is not None
                and canonical(observed) != canonical(implementation)):
            raise DecisionRuntimeError("current identity changed between sweep cells")
        implementation = observed
        configuration = {
            "method": "mcts", "mode": "serial_clockless", "seed": seed,
            "search_rng_mode": "new_seed_per_decision", "max_sims": sims,
            "horizon_rounds": horizon, "max_transitions": sims * horizon,
            "exploration": coefficient, "time_budget_ms": None, "priors": None,
            "parallel": False, "workers": None,
        }
        if version == 2:
            configuration.update(final_action_rule=rule,
                                 tie_break="root_encounter_order")
        statistics: list = []
        ranking: list[Action] = []
        elapsed = 0.0
        work = {"simulations": 0, "transitions": 0, "unused_transitions": 0,
                "stop_reasons": ["zero_requested_simulations"]}
        if sims:
            search = MCTS(horizon_rounds=horizon, max_sims=sims,
                          exploration=coefficient,
                          max_transitions=sims * horizon, rng=random.Random(seed))
            started = time.perf_counter()
            ranked = search.search(state, time_budget_ms=None, priors=None)
            elapsed = time.perf_counter() - started
            statistics, ranking, work = _statistics(
                search, ranked, state, sims, horizon)
        if not math.isfinite(elapsed) or elapsed < 0:
            raise DecisionRuntimeError("invalid elapsed search observation")
        if canonical(normalized(state)) != saved_state:
            raise DecisionRuntimeError(f"{pointer}: search changed selected root state")
        stored_identity = record["implementation"]
        comparisons: dict[str, Any] = {
            f"{name}_equal": canonical(implementation[f"{name}_sha256"]) ==
            canonical(stored_identity[f"{name}_sha256"])
            for name in ("engine_files", "example_files")
        }
        comparisons["runtime_fields_equal"] = canonical({
            name: implementation[name] for name in _RUNTIME_FIELDS}) == canonical({
                name: stored_identity[name] for name in _RUNTIME_FIELDS})
        comparisons["entrypoint_roles"] = {
            "recorded": "episode.py", "current": "decide_episode.py",
            "same_role": False,
        }
        base = {
            "format": "mcts-episode-decision-report", "schema_version": version,
            "status": "decision" if sims else "no_work", "search_performed": bool(sims),
            "source_record": {"bytes": len(data),
                              "sha256": hashlib.sha256(data).hexdigest()},
            "selection": {"step_index": step, "round_num": state.round_num,
                          "state_pointer": pointer},
            "selected_state": normalized(state), "stored_action": selected["action"],
            "stored_provenance": {name: record[name] for name in (
                "content", "scenario", "configuration", "implementation",
                "environment_rng")},
            "implementation": implementation, "identity_comparisons": comparisons,
            "value_semantics": VALUE_SEMANTICS,
        }
        report = finish_report(base, state, configuration, work, statistics, ranking,
                               elapsed)
        if version == 2:
            report["root_encounter_order"] = [
                {"card_idx": action.card_idx, "target_idx": action.target_idx}
                for action, visits, _ in statistics if visits]
            report["derivation"] = None
            if report["ranking"] != decision_ranking(report, "mean_visits"):
                raise DecisionRuntimeError(
                    "engine ranking disagrees with captured statistics")
            report["ranking"] = decision_ranking(report, rule)
            if report["ranking"]:
                chosen = report["ranking"][0]
                label = next(row["label"] for row in report["legal_actions"]
                             if row["card_idx"] == chosen["card_idx"] and
                             row["target_idx"] == chosen["target_idx"])
                report["recommendation"] = {**chosen, "label": label}
            validate_decision_report(report)
        output_bytes(report)
        if (canonical(normalized(state)) != saved_state
                or canonical(current_identity()) != canonical(implementation)):
            raise DecisionRuntimeError(
                "selected state or current identity changed during reporting")
        return report
    except DecisionRuntimeError:
        raise
    except (RuntimeError, OSError, ValueError, TypeError, KeyError,
            AttributeError, ArithmeticError, RecursionError, MemoryError) as exc:
        message = f"{pointer}: current decision failed ({exc})"
        raise DecisionRuntimeError(message) from exc


def episode_decision(record_path: Path, *, step: int, seed: int = 7,
                     sims: int = 16, horizon: int = 4,
                     exploration: float | None = None,
                     final_action_rule: str | None = None) -> dict:
    """Legacy V1 by default; explicit companion controls produce a V2 report."""
    from .episode_inspection import EXPLORATIONS, FINAL_ACTION_RULES
    from .episode_record import _choice, _number

    step = integer(step, "step", 0, 29)
    seed = integer(seed, "seed", SEED_MIN, SEED_MAX)
    sims = integer(sims, "sims", 0, 64)
    horizon = integer(horizon, "horizon", 1, 8)
    if exploration is not None:
        _number(exploration, "exploration", 0.6, 2.4)
        if exploration not in EXPLORATIONS:
            _input("exploration", "use 0.6, 1.2 or 2.4")
    if final_action_rule is not None:
        _choice(final_action_rule, "final_action_rule", FINAL_ACTION_RULES)
    data = _read(record_path, "record", RECORD_BYTES)
    record = validate_record(_parse(data, "record", 200_000, 10**300))
    return _decision_from_record(data, record, step=step, seed=seed, sims=sims,
                                 horizon=horizon, exploration=exploration,
                                 final_action_rule=final_action_rule)


def episode_stability(record_path: Path, *, step: int, seeds: list[int],
                      explorations: list[float] | None = None,
                      horizon: int = 4) -> dict:
    """One admitted state, a fixed grid, and explicit completed/incomplete output."""
    from .episode_inspection import (
        stability_configuration,
        stability_diagnostics,
        stability_work,
        validate_decision_report,
        validate_stability_report,
    )
    from .episode_record import _envelope

    config = stability_configuration(seeds, explorations if explorations is not None
                                     else [0.6, 1.2, 2.4], horizon)
    step = integer(step, "step", 0, 29)
    data = _read(record_path, "record", RECORD_BYTES)
    record = validate_record(_parse(data, "record", 200_000, 10**300))
    reference = _decision_from_record(
        data, record, step=step, seed=config["seeds"][0], sims=0, horizon=horizon,
        exploration=config["explorations"][0], final_action_rule="mean_visits")
    validate_decision_report(reference)
    cells: list[dict] = []
    report: dict[str, Any] = {
        "format": "mcts-episode-stability-report", "schema_version": 1,
        "status": "incomplete", "reference_decision": reference,
        "configuration": config, "cells": cells, "work": stability_work(cells),
        "diagnostics": None, "failure": None,
    }
    # Reserve repeated fixed payload, maximum choices and long numeric spellings
    # before search. Final byte and structural admission remain mandatory.
    placeholder = {**reference, "status": "decision", "search_performed": True,
                   "configuration": {**reference["configuration"], "seed": SEED_MIN,
                                     "max_sims": 64, "max_transitions": 512},
                   "work": {"simulations": 64, "transitions": 512,
                            "unused_transitions": 512,
                            "stop_reasons": ["simulation_cap", "transition_allowance"]},
                   "elapsed_seconds": 9.999999999999998e299,
                   "legal_actions": [{**row, "visits": 64,
                                      "value_sum": -9.999999999999998e299,
                                      "mean_shaped_reward": -9.999999999999998e299}
                                     for row in reference["legal_actions"]],
                   "root_encounter_order": [{"card_idx": row["card_idx"],
                                              "target_idx": row["target_idx"]}
                                             for row in reference["legal_actions"]]}
    placeholder["ranking"] = placeholder["root_encounter_order"]
    first = reference["legal_actions"][0]
    placeholder["recommendation"] = {name: first[name]
                                     for name in ("card_idx", "target_idx", "label")}
    preflight = {**report, "cells": [placeholder] * config["maximum_search_calls"],
                 "diagnostics": ["x" * 2048] * 8,
                 "failure": {"message": "x" * 2048}}
    output_bytes(preflight)
    _envelope(preflight, 200_000, 10**300)
    try:
        for coefficient in config["explorations"]:
            for seed in config["seeds"]:
                cell = _decision_from_record(
                    data, record, step=step, seed=seed, sims=64, horizon=horizon,
                    exploration=coefficient, final_action_rule="mean_visits",
                    implementation=reference["implementation"])
                validate_decision_report(cell)
                cells.append(cell)
        if canonical(current_identity()) != canonical(reference["implementation"]):
            raise DecisionRuntimeError(
                "current identity changed before sweep completion")
        report["work"] = stability_work(cells)
        report["diagnostics"] = stability_diagnostics(cells, config)
        report["status"] = "complete"
        validate_stability_report(report)
        output_bytes(report)
        return report
    except (KeyboardInterrupt, RuntimeError, OSError, ValueError, TypeError,
            KeyError, AttributeError, ArithmeticError, RecursionError,
            MemoryError) as exc:
        # The admitted prefix is the commit boundary, including interruptions
        # immediately after append. A separate pending counter can lag behind it.
        pending = (len(cells) if len(cells) < config["maximum_search_calls"]
                   else None)
        report["status"] = "incomplete"
        report["diagnostics"] = None
        report["work"] = stability_work(cells)
        report["failure"] = {
            "stage": "search" if pending is not None else "finalization",
            "cell_index": pending,
            "message": ("interrupted" if isinstance(exc, KeyboardInterrupt)
                        else str(exc)[:2048] or type(exc).__name__),
            "interrupted": isinstance(exc, KeyboardInterrupt),
        }
        validate_stability_report(report)
        output_bytes(report)
        return report
