"""Admit and read saved one-round reference reports without numerical work.

Stored values are checked for schema and internal arithmetic consistency. This
reader does not recompute transitions or authenticate the report's origin.
"""

from __future__ import annotations

import copy
import hashlib
import math
import re
from fractions import Fraction
from html import escape
from pathlib import Path
from typing import Any

from game import episode_inspection as inspection
from game import episode_record as records

from . import aggregation_domain

FORMAT = "mcts-one-round-reference-report"
MODEL = "independent_one_round_binary53_shaped_v1"
THREE_ENEMY_MODEL = "independent_one_round_three_enemy_binary53_shaped_v1"
PROBABILITY_MODEL = "iid_uniform_binary53_random_and_uniform_inclusive_integer"
VALUE_MODEL = "exact_expectation_of_source_order_binary64_shaped_reward"
REFERENCE_ENGINE_FILES_SHA256 = {
    "__init__.py": "099f37529017f01fe133417497ca038d72377633e8d8af98ef104b27b014b071",
    "actions.py": "468e9fd7373d91e285d2173acf89510bd11692419c80bc6aec4b0d0e04fcd618",
    "decider.py": "8d5c994f80abef9c8d6f1f83d524bb1bdd9792869b6d7f98770cb4318fcc0c3f",
    "mcts.py": "86902c63ed6a2f5bb8acb26413167947dbf2687bf4e7dfb911743851be35c04d",
    "parallel.py": "69769589192e740edaab83252766fb4dfb3d36a1d159571b4d415f2759d9f64b",
    "py.typed": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "rules.py": "ce82da2e1815dcdb7f4814012fae0c064152e3ad43c7da43743b2d50b5db588b",
    "simulator.py": "401390cd3373a063fe4a5c57f950617f598ec8d48fa5c680d1ae83a0c7c3a71d",
    "state.py": "b059f43ecb253bd03172bdd36b95420c0736d47a32e837c31ab747369a9e8cdc",
}
# The ownership documentation revision changes only the raw mcts.py docstring.
# Keep the original declaration available for passive historical report admission.
QUALIFIED_DOCUMENTATION_ENGINE_FILES_SHA256 = {
    "__init__.py": "099f37529017f01fe133417497ca038d72377633e8d8af98ef104b27b014b071",
    "actions.py": "468e9fd7373d91e285d2173acf89510bd11692419c80bc6aec4b0d0e04fcd618",
    "decider.py": "8d5c994f80abef9c8d6f1f83d524bb1bdd9792869b6d7f98770cb4318fcc0c3f",
    "mcts.py": "4cadf249dee661a535cd2d7eae0c9009caf91da88de69550292ca75b04b3c8ca",
    "parallel.py": "69769589192e740edaab83252766fb4dfb3d36a1d159571b4d415f2759d9f64b",
    "py.typed": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "rules.py": "ce82da2e1815dcdb7f4814012fae0c064152e3ad43c7da43743b2d50b5db588b",
    "simulator.py": "401390cd3373a063fe4a5c57f950617f598ec8d48fa5c680d1ae83a0c7c3a71d",
    "state.py": "b059f43ecb253bd03172bdd36b95420c0736d47a32e837c31ab747369a9e8cdc",
}
# Request-local reuse changes only construction of stable physical Action edges.
# Retain both earlier source declarations for historical report admission.
QUALIFIED_EDGE_REUSE_ENGINE_FILES_SHA256 = {
    "__init__.py": "099f37529017f01fe133417497ca038d72377633e8d8af98ef104b27b014b071",
    "actions.py": "468e9fd7373d91e285d2173acf89510bd11692419c80bc6aec4b0d0e04fcd618",
    "decider.py": "8d5c994f80abef9c8d6f1f83d524bb1bdd9792869b6d7f98770cb4318fcc0c3f",
    "mcts.py": "2a53a16dc96dfaba6ed408a54598bfb61257fe42194d8cf828e11db68761c927",
    "parallel.py": "69769589192e740edaab83252766fb4dfb3d36a1d159571b4d415f2759d9f64b",
    "py.typed": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "rules.py": "ce82da2e1815dcdb7f4814012fae0c064152e3ad43c7da43743b2d50b5db588b",
    "simulator.py": "401390cd3373a063fe4a5c57f950617f598ec8d48fa5c680d1ae83a0c7c3a71d",
    "state.py": "b059f43ecb253bd03172bdd36b95420c0736d47a32e837c31ab747369a9e8cdc",
}
# Root-specific allocation changes sampling and final selection only. Its
# horizon-one payoff, simulator, rollout and ordinary default were independently
# qualified against the retained one-round reference before product integration.
# Admission remains an exact complete source map, including all dependencies.
QUALIFIED_ROOT_ALLOCATION_ENGINE_FILES_SHA256 = {
    **QUALIFIED_EDGE_REUSE_ENGINE_FILES_SHA256,
    "mcts.py": "9be3ddafc78bbb617b232f733bc5dc7932b02ebafdd5d205273f604269af2c12",
}
# Git's literal committed body uses LF. The exact CRLF-to-LF source conversion
# was separately qualified, preserving the evaluated body above and every
# dependency. Both complete maps remain explicit, with no generic normalization.
QUALIFIED_CANONICAL_ROOT_ALLOCATION_ENGINE_FILES_SHA256 = {
    **QUALIFIED_EDGE_REUSE_ENGINE_FILES_SHA256,
    "mcts.py": "153e0c6b2f1b5ab1baeb92496ec19860b97b48008b177ce924c134d190cbf0f8",
}
# The reviewed managed wrapper forwards the existing root treatment and exposes
# detached diagnostics. Its ordinary default, lifecycle, simulator and reward
# remain unchanged. All eight other canonical members retain the prior map.
QUALIFIED_CANONICAL_MANAGED_ROOT_ALLOCATION_ENGINE_FILES_SHA256 = {
    **QUALIFIED_CANONICAL_ROOT_ALLOCATION_ENGINE_FILES_SHA256,
    "decider.py": "a9a98022b1bad9db04bcb649aeb110c609f81347155820a566deb3abf3582ac5",
}
# This complete Windows CRLF map is the exact frozen encounter-study identity.
# Each body has the separately qualified CRLF-to-LF byte and AST equivalence to
# the canonical managed map. Runtime admission never normalizes an unknown map.
QUALIFIED_WINDOWS_MANAGED_ROOT_ALLOCATION_ENGINE_FILES_SHA256 = {
    "__init__.py": "800fcdd9109e848efdc004bcc48743826fccf202bae11188041a9be01e75737a",
    "actions.py": "9d3af9c4ef9ca1a9cba3acde9291d56a18742b1fd9785db34954fcdc8d325e24",
    "decider.py": "eebbcc25f5ad6add9769b436bd8569841305c0f3a42ec68e2c79003c2fca6d17",
    "mcts.py": "9be3ddafc78bbb617b232f733bc5dc7932b02ebafdd5d205273f604269af2c12",
    "parallel.py": "529741961928c8554dac3755cd191a8bd0275c15c250465f39ddad9b08185189",
    "py.typed": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "rules.py": "fc18fb059461020922b54a59da1f5f3856280daf960735174e55289da3ded6d4",
    "simulator.py": "6bb0fe967262e62816f35224448ae6a9397181cb59db3800c6f43e0257233c7d",
    "state.py": "4e1345f0d4e5fede83eebf1d5a149360c8aced07dc82c1afe2a885facc23c762",
}
# Exact below-half health changes only the boss-rule threshold. The existing
# physical and adaptive reference domains exclude all boss rules. Their finite
# calculations are qualified against this complete new source map without
# rewriting any historical declaration or extending the supported states.
QUALIFIED_CANONICAL_EXACT_HALF_ENGINE_FILES_SHA256 = {
    **QUALIFIED_CANONICAL_MANAGED_ROOT_ALLOCATION_ENGINE_FILES_SHA256,
    "rules.py": "61c52b9ad9f54a5f37b4e1a063dd285a3f0a07a8263a038241161439005ce211",
}
# This separately checked all-CRLF projection is an exact complete map. Runtime
# admission still compares literal hashes and never normalizes unknown source.
QUALIFIED_WINDOWS_EXACT_HALF_ENGINE_FILES_SHA256 = {
    **QUALIFIED_WINDOWS_MANAGED_ROOT_ALLOCATION_ENGINE_FILES_SHA256,
    "rules.py": "0a098f932f51c8f529cdb37c2b296464fe43b41d1b341acbcf5da9425fe83d1c",
}
SEARCH_VALUE_SEMANTICS = (
    "MCTS terminal wins score 1 - 0.045 * min(6, depth); "
    "terminal losses score 0.15 * min(depth, h) / h, where "
    "h = max(1, horizon_rounds). One-round terminal wins score 1 and losses 0. "
    "Ongoing horizon states use the existing HP/setup heuristic. "
    "Means are shaped simulator rewards, not calibrated win probabilities. "
    "One-round samples are not MCTS visits."
)
BASE_FIELDS = {
    "format",
    "schema_version",
    "source_report",
    "decision_report",
    "selected_state_sha256",
    "implementation",
    "identity_comparisons",
    "model",
    "horizon_rounds",
    "terminal_depth",
    "probability_model",
    "value_model",
    "limits",
    "new_search_performed",
    "reference_engine_files_sha256",
}
EVALUATION_FIELDS = {
    "model",
    "horizon_rounds",
    "terminal_depth",
    "actions",
    "best_actions",
    "total_leaves",
    "elapsed_seconds",
    "probability_model",
    "value_model",
}
AGGREGATION_WORK_FIELDS = {
    "contributions",
    "payoff_evaluations",
    "peak_bins",
    "represented_damage_combinations",
    "represented_trace_leaves",
}
RUNTIME_FIELDS = (
    "python",
    "python_implementation",
    "platform",
    "engine_import_kind",
    "distribution_version",
    "distribution_matches_import",
    "machine",
    "pointer_bits",
    "python_full_version",
    "python_build",
    "python_cache_tag",
    "rng_state_version",
)
REFUSAL_KINDS = {
    "horizon_mismatch",
    "unsupported_state",
    "work_limit",
    "interrupted",
    "runtime_failure",
    "engine_mismatch",
    "identity_changed",
}
_INTEGER_TEXT = re.compile(r"(?:0|-[1-9][0-9]*|[1-9][0-9]*)\Z")
_POSITIVE_TEXT = re.compile(r"[1-9][0-9]*\Z")
FRACTION_DIGITS = 2048
ELEMENTS = {"ember", "frost", "gale", "rune", "verdant", "shade", "aether", "neutral"}


def _qualified_card(card: dict, location: str) -> None:
    records._string(card["name"], location + "/name")
    records.integer(card["pip_cost"], location + "/pip_cost", 0, 14)
    records._number(card["accuracy"], location + "/accuracy", 0, 1)
    if card["accuracy"] == 0:
        records._error(location + "/accuracy", "loader cards require positive accuracy")
    for name in ("damage_min", "damage_max", "heal", "dot_tick"):
        records.integer(card[name], location + "/" + name, 0, 1_000_000)
    records.integer(card["dot_rounds"], location + "/dot_rounds", 0, 30)
    if not 1 <= card["damage_max"] - card["damage_min"] + 1 <= 151:
        records._error(location, "require ordered damage with at most 151 outcomes")
    if (card["dot_tick"] > 0) != (card["dot_rounds"] > 0):
        records._error(location, "damage-over-time fields must agree")
    records._number(card["modifier"], location + "/modifier", -2, 2)
    if card["card_type"] == "damage" and card["damage_max"] == 0:
        records._error(location, "damage cards require positive damage")
    if card["card_type"] == "heal" and card["heal"] == 0:
        records._error(location, "heal cards require positive restoration")
    if card["card_type"] in {"blade", "trap", "shield"} and card["modifier"] <= 0:
        records._error(location, "modifier cards require a positive modifier")


def _qualified_fighter(fighter: dict, location: str) -> None:
    records._string(fighter["name"], location + "/name")
    maximum = records.integer(fighter["max_hp"], location + "/max_hp", 1, 1_000_000)
    records.integer(fighter["hp"], location + "/hp", 1, maximum)
    for name in ("pips", "power_pips"):
        records.integer(fighter[name], location + "/" + name, 0, 7)
    if fighter["pips"] + fighter["power_pips"] > 7:
        records._error(location, "at most seven resource slots are supported")
    records._number(fighter["power_pip_chance"], location + "/power_pip_chance", 0, 1)
    for name in ("resist", "boost"):
        if set(fighter[name]) - ELEMENTS:
            records._error(location + "/" + name, "unknown element key")
        for element, value in fighter[name].items():
            records._number(value, location + "/" + name + "/" + element, -1, 1)
    for name, low, high in (("blades", 0, 2), ("traps", 0, 2), ("shields", -2, 0)):
        for index, charm in enumerate(
            records._array(fighter[name], location + "/" + name, 0, 4)
        ):
            records._number(
                charm["value"], f"{location}/{name}/{index}/value", low, high
            )
    for index, dot in enumerate(
        records._array(fighter["dots"], location + "/dots", 0, 4)
    ):
        records.integer(dot["tick"], f"{location}/dots/{index}/tick", 0, 1_000_000)
        records.integer(
            dot["rounds_left"], f"{location}/dots/{index}/rounds_left", 1, 30
        )
    if fighter["is_boss"] is not False or fighter["policy"] is not None:
        records._error(location, "boss flags and opponent policies are excluded")
    if fighter["base_attack"] is not None:
        _qualified_card(fighter["base_attack"], location + "/base_attack")
        if fighter["base_attack"]["card_type"] != "damage":
            records._error(location + "/base_attack", "must be a damage card")


def _qualified_state(state: dict, *, model: str = MODEL) -> None:
    """Admit the whole declared root subset without importing the numerical core."""
    location = "/decision_report/selected_state"
    records.integer(state["round_num"], location + "/round_num", 1, 30)
    if state["boss_rules"] != []:
        records._error(location + "/boss_rules", "rules are outside this model")
    _qualified_fighter(state["player"], location + "/player")
    minimum, maximum = (3, 3) if model == THREE_ENEMY_MODEL else (1, 2)
    enemies = records._array(state["enemies"], location + "/enemies", minimum, maximum)
    affordable = 0
    for index, enemy in enumerate(enemies):
        _qualified_fighter(enemy, f"{location}/enemies/{index}")
        attack = enemy["base_attack"]
        element = "neutral" if attack is None else attack["element"]
        cost = 3 if attack is None else attack["pip_cost"]
        multiplier = 2 if element == enemy["element"] else 1
        affordable += enemy["pips"] + multiplier * enemy["power_pips"] >= cost
    if affordable > 1:
        records._error(
            location + "/enemies", "at most one affordable response is supported"
        )
    for index, card in enumerate(
        records._array(state["hand"], location + "/hand", 0, 7)
    ):
        _qualified_card(card, f"{location}/hand/{index}")


def _same(left: Any, right: Any) -> bool:
    return records.canonical(left) == records.canonical(right)


def qualified_engine_files(value: Any) -> bool:
    """Admit an independently qualified complete raw-source map."""
    return isinstance(value, dict) and any(
        _same(value, admitted)
        for admitted in (
            REFERENCE_ENGINE_FILES_SHA256,
            QUALIFIED_DOCUMENTATION_ENGINE_FILES_SHA256,
            QUALIFIED_EDGE_REUSE_ENGINE_FILES_SHA256,
            QUALIFIED_ROOT_ALLOCATION_ENGINE_FILES_SHA256,
            QUALIFIED_CANONICAL_ROOT_ALLOCATION_ENGINE_FILES_SHA256,
            QUALIFIED_CANONICAL_MANAGED_ROOT_ALLOCATION_ENGINE_FILES_SHA256,
            QUALIFIED_WINDOWS_MANAGED_ROOT_ALLOCATION_ENGINE_FILES_SHA256,
            QUALIFIED_CANONICAL_EXACT_HALF_ENGINE_FILES_SHA256,
            QUALIFIED_WINDOWS_EXACT_HALF_ENGINE_FILES_SHA256,
        )
    )


def _fraction(value: Any, location: str, *, probability: bool = False) -> Fraction:
    obj = records._object(value, location, {"numerator", "denominator"})
    for name, pattern in (
        ("numerator", _INTEGER_TEXT),
        ("denominator", _POSITIVE_TEXT),
    ):
        text = records._string(obj[name], f"{location}/{name}", high=FRACTION_DIGITS)
        if pattern.fullmatch(text) is None:
            records._error(f"{location}/{name}", "use canonical decimal text")
    numerator, denominator = int(obj["numerator"]), int(obj["denominator"])
    if math.gcd(numerator, denominator) != 1:
        records._error(location, "fraction must be reduced")
    result = Fraction(numerator, denominator)
    if probability and not 0 <= result <= 1:
        records._error(location, "must be in the exact interval 0..1")
    return result


def _fraction_object(value: Fraction) -> dict:
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def _action(value: Any, location: str) -> tuple:
    return inspection._report_action(value, location)


def _identity(value: dict) -> tuple:
    return value["card_idx"], value["target_idx"]


def _physical_actions(state: dict) -> list[dict]:
    """Check saved index coverage with no transition, scoring or search calls."""
    actions = [{"card_idx": None, "target_idx": None}]
    player = state["player"]
    if player["hp"] <= 0:
        return actions
    for index, card in enumerate(state["hand"]):
        multiplier = 2 if card["element"] == player["element"] else 1
        available = player["pips"] + multiplier * player["power_pips"]
        if available < card["pip_cost"]:
            continue
        if card["card_type"] in {"heal", "blade", "shield"} or card["hits_all"]:
            targets = [None]
        elif card["card_type"] in {"damage", "trap"}:
            targets = [i for i, enemy in enumerate(state["enemies"]) if enemy["hp"] > 0]
        else:
            targets = [None]
        actions.extend({"card_idx": index, "target_idx": target} for target in targets)
    return actions


def _implementation(value: Any) -> dict:
    location = "/implementation"
    obj = records._object(
        value,
        location,
        {
            "decision_consumer",
            "reference_files_sha256",
            "entrypoint_files_sha256",
        },
    )
    inspection._report_implementation(
        obj["decision_consumer"], location + "/decision_consumer"
    )
    files = obj["reference_files_sha256"]
    records._hash_map(files, location + "/reference_files_sha256")
    required = {
        "reference/__init__.py",
        "reference/consumer.py",
        "reference/one_round.py",
        "reference/report.py",
    }
    if (
        not 4 <= len(files) <= 16
        or not required <= set(files)
        or any(
            re.fullmatch(r"reference/[A-Za-z_][A-Za-z0-9_]*\.py", name) is None
            for name in files
        )
    ):
        records._error(
            location + "/reference_files_sha256",
            "identify every bounded reference module by relative name",
        )
    entry = obj["entrypoint_files_sha256"]
    records._hash_map(entry, location + "/entrypoint_files_sha256")
    if set(entry) != {"reference_episode.py"}:
        records._error(
            location + "/entrypoint_files_sha256", "must identify reference_episode.py"
        )
    return obj


def _comparisons(decision: dict, implementation: dict) -> dict:
    current = implementation["decision_consumer"]
    search = decision["implementation"]
    return {
        "search_engine_files_equal": _same(
            search["engine_files_sha256"], current["engine_files_sha256"]
        ),
        "search_producer_equal": _same(search, current),
        "entrypoint_roles": {
            "search": "decide_episode.py",
            "reference": "reference_episode.py",
            "same_role": False,
        },
    }


def _saved_identity_comparisons(decision: dict) -> None:
    search = decision["implementation"]
    recorded = decision["stored_provenance"]["implementation"]
    expected = {
        f"{name}_equal": _same(search[name + "_sha256"], recorded[name + "_sha256"])
        for name in ("engine_files", "example_files")
    }
    expected["runtime_fields_equal"] = _same(
        {name: search[name] for name in RUNTIME_FIELDS},
        {name: recorded[name] for name in RUNTIME_FIELDS},
    )
    expected["entrypoint_roles"] = {
        "recorded": "episode.py",
        "current": "decide_episode.py",
        "same_role": False,
    }
    if not _same(decision["identity_comparisons"], expected):
        records._error(
            "/decision_report/identity_comparisons",
            "does not match the nested saved implementation identities",
        )


def _limits(value: Any) -> dict:
    obj = records._object(
        value,
        "/limits",
        {
            "max_paths",
            "max_total_paths",
            "max_seconds",
        },
    )
    records.integer(obj["max_paths"], "/limits/max_paths", 1, 250_000)
    records.integer(obj["max_total_paths"], "/limits/max_total_paths", 1, 1_000_000)
    records._number(obj["max_seconds"], "/limits/max_seconds", 0.000001, 30)
    return obj


def _aggregation_limits(value: Any) -> dict:
    obj = records._object(
        value,
        "/limits",
        {"max_contributions", "max_payoff_evaluations", "max_seconds"},
    )
    records.integer(obj["max_contributions"], "/limits/max_contributions", 1, 1_000_000)
    records.integer(
        obj["max_payoff_evaluations"], "/limits/max_payoff_evaluations", 1, 10_000
    )
    records._number(obj["max_seconds"], "/limits/max_seconds", 0, 30)
    if obj["max_seconds"] == 0:
        records._error("/limits/max_seconds", "require a finite positive deadline")
    return obj


def _base_fields(value: Any) -> set[str]:
    fields = BASE_FIELDS.copy()
    if isinstance(value, dict) and value.get("schema_version") == 2:
        fields.add("computation_method")
    return fields


def _computation_method(value: dict) -> str:
    return value.get("computation_method", aggregation_domain.PHYSICAL_METHOD)


def _model(value: dict, location: str = "", *, model: str | None = None) -> None:
    records._choice(value["model"], location + "/model", {MODEL, THREE_ENEMY_MODEL})
    if model is not None and value["model"] != model:
        records._error(location + "/model", "must match the report's selected model")
    for name, expected in (
        ("probability_model", PROBABILITY_MODEL),
        ("value_model", VALUE_MODEL),
    ):
        records._choice(value[name], location + "/" + name, {expected})
    for name in ("horizon_rounds", "terminal_depth"):
        records.integer(value[name], location + "/" + name, 1, 1)


def _validate_base(value: Any, *, envelope: bool = True) -> dict:
    if envelope:
        records._envelope(value, 250_000, 10**300)
    obj = records._object(value, "/report", _base_fields(value))
    records._choice(obj["format"], "/format", {FORMAT})
    records.integer(obj["schema_version"], "/schema_version", 1, 2)
    if obj["schema_version"] == 2:
        records._choice(
            obj["computation_method"],
            "/computation_method",
            {aggregation_domain.METHOD},
        )
    _model(obj)
    if not qualified_engine_files(obj["reference_engine_files_sha256"]):
        records._error(
            "/reference_engine_files_sha256",
            "must identify the engine bodies qualified for this model",
        )
    if obj["schema_version"] == 2:
        _aggregation_limits(obj["limits"])
    else:
        _limits(obj["limits"])
    if obj["new_search_performed"] is not False:
        records._error("/new_search_performed", "reference evaluation runs no search")
    decision = inspection.validate_decision_report(obj["decision_report"])
    _saved_identity_comparisons(decision)
    source = records._object(
        obj["source_report"],
        "/source_report",
        {
            "bytes",
            "sha256",
            "canonical_sha256",
        },
    )
    records.integer(source["bytes"], "/source_report/bytes", 1, records.RECORD_BYTES)
    for name in ("sha256", "canonical_sha256"):
        records._digest(source[name], "/source_report/" + name)
    canonical_digest = hashlib.sha256(records.canonical(decision)).hexdigest()
    if source["canonical_sha256"] != canonical_digest:
        records._error(
            "/source_report/canonical_sha256",
            "does not bind the nested saved decision representation",
        )
    records._digest(obj["selected_state_sha256"], "/selected_state_sha256")
    state_digest = hashlib.sha256(
        records.canonical(decision["selected_state"])
    ).hexdigest()
    if obj["selected_state_sha256"] != state_digest:
        records._error("/selected_state_sha256", "does not bind the exact saved state")
    implementation = _implementation(obj["implementation"])
    if obj["schema_version"] == 2 and not {
        "reference/aggregation.py",
        "reference/aggregation_domain.py",
    } <= set(implementation["reference_files_sha256"]):
        records._error(
            "/implementation/reference_files_sha256",
            "the aggregation producer must identify its calculation and domain modules",
        )
    expected = _comparisons(decision, implementation)
    if not _same(obj["identity_comparisons"], expected):
        records._error(
            "/identity_comparisons", "does not match the saved producer identities"
        )
    return obj


def reference_report_base(
    decision: dict,
    captured: bytes,
    implementation: dict,
    limits: dict,
    *,
    model: str = MODEL,
    computation_method: str = aggregation_domain.PHYSICAL_METHOD,
) -> dict:
    """Bind a validated saved decision and observed producer before evaluation."""
    records._choice(model, "/model", {MODEL, THREE_ENEMY_MODEL})
    records._choice(
        computation_method,
        "/computation_method",
        {aggregation_domain.PHYSICAL_METHOD, aggregation_domain.METHOD},
    )
    decision = inspection.validate_decision_report(decision)
    if (
        not isinstance(captured, bytes)
        or not 1 <= len(captured) <= records.RECORD_BYTES
    ):
        records._error("source report", "require bounded nonempty captured bytes")
    parsed = inspection.validate_decision_report(
        records._parse(captured, "source decision report", 200_000, 10**300)
    )
    if not _same(parsed, decision):
        records._error("source report", "captured input differs from supplied decision")
    implementation = _implementation(implementation)
    observed_engine = implementation["decision_consumer"]["engine_files_sha256"]
    qualified_engine = (
        observed_engine
        if qualified_engine_files(observed_engine)
        else REFERENCE_ENGINE_FILES_SHA256
    )
    base = {
        "format": FORMAT,
        "schema_version": 1,
        "source_report": {
            "bytes": len(captured),
            "sha256": hashlib.sha256(captured).hexdigest(),
            "canonical_sha256": hashlib.sha256(records.canonical(decision)).hexdigest(),
        },
        "decision_report": copy.deepcopy(decision),
        "selected_state_sha256": hashlib.sha256(
            records.canonical(decision["selected_state"])
        ).hexdigest(),
        "implementation": copy.deepcopy(implementation),
        "identity_comparisons": _comparisons(decision, implementation),
        "model": model,
        "horizon_rounds": 1,
        "terminal_depth": 1,
        "probability_model": PROBABILITY_MODEL,
        "value_model": VALUE_MODEL,
        "limits": copy.deepcopy(limits),
        "new_search_performed": False,
        "reference_engine_files_sha256": copy.deepcopy(qualified_engine),
    }
    if computation_method == aggregation_domain.METHOD:
        base["schema_version"] = 2
        base["computation_method"] = computation_method
    return _validate_base(base)


def _evaluation(
    value: Any,
    decision: dict,
    limits: dict,
    *,
    model: str = MODEL,
    computation_method: str = aggregation_domain.PHYSICAL_METHOD,
) -> dict:
    aggregate = computation_method == aggregation_domain.METHOD
    fields = (
        EVALUATION_FIELDS - {"total_leaves"} | {"work"}
        if aggregate
        else EVALUATION_FIELDS
    )
    obj = records._object(value, "/evaluation", fields)
    _model(obj, "/evaluation", model=model)
    if decision["configuration"]["horizon_rounds"] != 1:
        records._error(
            "/decision_report/configuration/horizon_rounds",
            "a complete comparison requires one-round search",
        )
    state = decision["selected_state"]
    _qualified_state(state, model=model)
    if aggregate:
        try:
            aggregation_domain.qualify(state)
        except ValueError as exc:
            records._error("/decision_report/selected_state", str(exc))
    action_limit = 22 if model == THREE_ENEMY_MODEL else 15
    expected_actions = _physical_actions(state)
    saved_actions = [
        {name: row[name] for name in ("card_idx", "target_idx")}
        for row in decision["legal_actions"]
    ]
    if not _same(saved_actions, expected_actions):
        records._error(
            "/decision_report/legal_actions",
            "must retain every legal physical choice in stored order",
        )
    values = []
    actions = []
    total = 0
    total_work = dict.fromkeys(AGGREGATION_WORK_FIELDS, 0)
    for index, row in enumerate(
        records._array(obj["actions"], "/evaluation/actions", 1, action_limit)
    ):
        path = f"/evaluation/actions/{index}"
        row_fields = {
            "action",
            "expected_value",
            "expected_value_float",
            "mass",
            "win_mass",
            "loss_mass",
            "ongoing_mass",
            "work" if aggregate else "leaves",
        }
        row = records._object(
            row,
            path,
            row_fields,
        )
        _action(row["action"], path + "/action")
        actions.append(row["action"])
        value = _fraction(
            row["expected_value"], path + "/expected_value", probability=True
        )
        values.append(value)
        records._number(
            row["expected_value_float"], path + "/expected_value_float", 0, 1
        )
        if row["expected_value_float"] != float(value):
            records._error(
                path + "/expected_value_float",
                "must be derived from the exact fraction",
            )
        if _fraction(row["mass"], path + "/mass", probability=True) != 1:
            records._error(path + "/mass", "complete action mass must be one")
        masses = [
            _fraction(row[name], path + "/" + name, probability=True)
            for name in ("win_mass", "loss_mass", "ongoing_mass")
        ]
        if sum(masses, Fraction(0)) != 1:
            records._error(path, "terminal and ongoing masses must sum to one")
        terminal_value = (
            Fraction.from_float(1.0 - 0.045) * masses[0]
            + Fraction.from_float(0.15) * masses[1]
        )
        if not terminal_value <= value <= terminal_value + masses[2]:
            records._error(
                path + "/expected_value",
                "must respect terminal payoffs and ongoing score bounds",
            )
        if aggregate:
            if masses != [Fraction(0), Fraction(0), Fraction(1)]:
                records._error(
                    path, "the sum-convolution domain retains only ongoing outcomes"
                )
            if index >= len(expected_actions) or not _same(
                row["action"], expected_actions[index]
            ):
                records._error(
                    path + "/action",
                    "must retain the legal physical action at this index",
                )
            work = records._object(row["work"], path + "/work", AGGREGATION_WORK_FIELDS)
            expected_work = aggregation_domain.action_work(state, row["action"])
            for name in AGGREGATION_WORK_FIELDS:
                records.integer(work[name], path + "/work/" + name, 0, 10**300)
            if not _same(work, expected_work):
                records._error(
                    path + "/work",
                    "must retain the declared method's exact work accounting",
                )
            for name in AGGREGATION_WORK_FIELDS:
                total_work[name] = (
                    max(total_work[name], work[name])
                    if name == "peak_bins"
                    else total_work[name] + work[name]
                )
        else:
            total += records.integer(
                row["leaves"], path + "/leaves", 1, limits["max_paths"]
            )
    if not _same(actions, expected_actions):
        records._error(
            "/evaluation/actions", "must price the complete ordered physical action set"
        )
    maximum = max(values)
    best = [
        action
        for action, value in zip(actions, values, strict=True)
        if value == maximum
    ]
    for index, action in enumerate(
        records._array(obj["best_actions"], "/evaluation/best_actions", 1, action_limit)
    ):
        _action(action, f"/evaluation/best_actions/{index}")
    if not _same(obj["best_actions"], best):
        records._error(
            "/evaluation/best_actions",
            "must retain every exact maximum in physical action order",
        )
    if aggregate:
        work = records._object(obj["work"], "/evaluation/work", AGGREGATION_WORK_FIELDS)
        for name in AGGREGATION_WORK_FIELDS:
            records.integer(work[name], "/evaluation/work/" + name, 0, 10**300)
        if not _same(work, total_work):
            records._error(
                "/evaluation/work",
                "must sum action work and retain the maximum individual bin support",
            )
        for name in ("contributions", "payoff_evaluations"):
            if work[name] > limits["max_" + name]:
                records._error(
                    "/evaluation/work/" + name, "exceeds the declared work limit"
                )
    else:
        records.integer(
            obj["total_leaves"],
            "/evaluation/total_leaves",
            1,
            limits["max_total_paths"],
        )
        if obj["total_leaves"] != total:
            records._error("/evaluation/total_leaves", "must equal the action leaf sum")
    records._number(
        obj["elapsed_seconds"], "/evaluation/elapsed_seconds", 0, limits["max_seconds"]
    )
    return obj


def _diagnostics(base: dict, evaluation: dict) -> dict:
    decision = base["decision_report"]
    values = {
        _identity(row["action"]): _fraction(
            row["expected_value"], "/evaluation/expected_value", probability=True
        )
        for row in evaluation["actions"]
    }
    maximum = max(values.values())

    def price(action: dict | None) -> dict | None:
        if action is None:
            return None
        identity = {name: action[name] for name in ("card_idx", "target_idx")}
        value = values[_identity(identity)]
        loss = maximum - value
        return {
            "action": identity,
            "expected_value": _fraction_object(value),
            "value_loss": _fraction_object(loss),
            "value_loss_float": float(loss),
            "reference_best": loss == 0,
        }

    selectors = None
    if decision["schema_version"] == 2:
        selectors = {}
        for rule in ("mean_visits", "visits_mean"):
            ranked = inspection.decision_ranking(decision, rule)
            selectors[rule] = price(ranked[0] if ranked else None)
    reasons = []
    if not base["identity_comparisons"]["search_engine_files_equal"]:
        reasons.append("search_engine_identity_differs")
    if decision["value_semantics"] != SEARCH_VALUE_SEMANTICS:
        reasons.append("search_value_declaration_differs")
    return {
        "recommendation": price(decision["recommendation"]),
        "same_statistics": selectors,
        "comparison_eligibility": {"eligible": not reasons, "reasons": reasons},
    }


def complete_reference_report(base: dict, evaluation: dict) -> dict:
    """Finish only after every admitted action has a complete finite value."""
    base = _validate_base(base)
    evaluation = _evaluation(
        evaluation,
        base["decision_report"],
        base["limits"],
        model=base["model"],
        computation_method=_computation_method(base),
    )
    value = {
        **copy.deepcopy(base),
        "status": "complete",
        "evaluation": copy.deepcopy(evaluation),
        "diagnostics": _diagnostics(base, evaluation),
        "failure": None,
    }
    return validate_reference_report(value)


def refused_reference_report(base: dict, kind: str, message: str) -> dict:
    """Retain the input and limits without exposing partially priced actions."""
    base = _validate_base(base)
    value = {
        **copy.deepcopy(base),
        "status": "refused",
        "evaluation": None,
        "diagnostics": None,
        "failure": {"kind": kind, "message": message},
    }
    return validate_reference_report(value)


def validate_reference_report(value: Any) -> dict:
    """Check saved schema and derived fractions without running the reference."""
    if (
        isinstance(value, dict)
        and value.get("format") == "mcts-two-round-adaptive-reference-report"
    ):
        from .adaptive_report import validate_reference_report as validate_adaptive

        return validate_adaptive(value)
    records._envelope(value, 250_000, 10**300)
    obj = records._object(
        value,
        "/report",
        _base_fields(value)
        | {
            "status",
            "evaluation",
            "diagnostics",
            "failure",
        },
    )
    base = _validate_base(
        {name: obj[name] for name in _base_fields(obj)}, envelope=False
    )
    records._choice(obj["status"], "/status", {"complete", "refused"})
    if obj["status"] == "refused":
        if obj["evaluation"] is not None or obj["diagnostics"] is not None:
            records._error(
                "/evaluation", "refusal cannot retain accepted partial values"
            )
        failure = records._object(obj["failure"], "/failure", {"kind", "message"})
        records._choice(failure["kind"], "/failure/kind", REFUSAL_KINDS)
        records._string(failure["message"], "/failure/message", high=2048)
        if (
            failure["kind"] == "horizon_mismatch"
            and obj["decision_report"]["configuration"]["horizon_rounds"] == 1
        ):
            records._error("/failure/kind", "horizon_mismatch requires another horizon")
    else:
        if obj["failure"] is not None:
            records._error("/failure", "a complete report requires null")
        if not _same(
            obj["implementation"]["decision_consumer"]["engine_files_sha256"],
            obj["reference_engine_files_sha256"],
        ):
            records._error(
                "/implementation/decision_consumer/engine_files_sha256",
                "complete values require the qualified engine bodies",
            )
        evaluation = _evaluation(
            obj["evaluation"],
            base["decision_report"],
            base["limits"],
            model=base["model"],
            computation_method=_computation_method(base),
        )
        if not _same(obj["diagnostics"], _diagnostics(base, evaluation)):
            records._error(
                "/diagnostics", "must derive choices and exact losses from saved values"
            )
    return obj


def _capture(path: Path, role: str) -> tuple[dict, bytes]:
    captured = records._read(path, role, records.RECORD_BYTES)
    value = records._parse(captured, role, 250_000, 10**300)
    return validate_reference_report(value), captured


def _appearance(value: str) -> None:
    if not isinstance(value, str) or value not in inspection.THEMES:
        records._error("appearance", "choose obscur or clair")


def _start(title: str, appearance: str) -> inspection._Document:
    document = inspection._Document()
    document.add(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>"
        + title
        + "</title><style>"
        + inspection._css(appearance)
        + "</style></head><body><main>"
    )
    return document


def _finish(document: inspection._Document) -> bytes:
    document.add(
        "<footer><p>Passive admission checks schema and stored arithmetic "
        "consistency. It does not authenticate origin or rerun the "
        "reference. The original source byte hash is a stored claim "
        "unless those bytes are supplied separately. Exact fractions "
        "remain decimal strings. Displayed decimals do not rank actions. "
        "No script, network request, font download or search runs here.</p>"
        "<p>Local Inter is used when available, with Arial and sans-serif "
        "fallback. Screen appearance is fixed. Print uses Clair.</p>"
        "</footer></main></body></html>"
    )
    return document.finish()


def _meaning(document: inspection._Document, record: dict, *, prefix: str) -> None:
    document.add(
        f'<section id="{prefix}meaning"><h2>Model, objective and limits</h2>'
        "<p>These are complete finite expectations after one round under "
        "the declared independent draw law. Every payoff preserves the source "
        "order binary64 shaped reward. A loss is the best expected shaped "
        "value minus the chosen action's value. It is not lost win "
        "probability, full encounter optimality or proof of a stronger "
        "default. The idealized law is not a theorem about all seeded "
        "generator streams.</p>"
    )
    inspection._facts(
        document,
        [
            ("Report status", record["status"]),
            ("Model", record["model"]),
            ("Computation method", _computation_method(record)),
            (
                "Admitted initial enemy subset",
                "Exactly three living enemies"
                if record["model"] == THREE_ENEMY_MODEL
                else "One or two living enemies",
            ),
            ("Probability law", record["probability_model"]),
            ("Value objective", record["value_model"]),
            ("Complete round horizon", record["horizon_rounds"]),
            ("Terminal depth", record["terminal_depth"]),
            ("New search performed", record["new_search_performed"]),
            ("Operational limits", record["limits"]),
        ],
    )
    document.add(
        "<p>The time limit is cooperative. It is checked by the numerical "
        "consumer and is not a hard external wall or memory bound. A "
        "work cap or cancellation refuses the whole report. An admitted "
        "wide action can still exceed the work limit.</p>"
    )
    if record["schema_version"] == 2:
        document.add(
            "<p>Integer sum convolution counts damage multiplicities and evaluates "
            "the source-order payoff at every total. The narrower admitted domain "
            "has no responses, effects or lethal damage. Final regeneration is "
            "summed out for values and outcome masses only. Executed contribution "
            "updates and payoff evaluations are separate from represented damage "
            "tuples and positive physical trace leaves. Represented traces were "
            "not enumerated. This report supplies no successor distribution, "
            "draw tape, measured speedup or stronger decision claim.</p>"
        )
    document.add("</section>")


def _values(document: inspection._Document, record: dict, *, prefix: str) -> None:
    document.add(f'<section id="{prefix}values"><h2>Complete action values</h2>')
    if record["status"] == "refused":
        inspection._facts(
            document,
            [
                ("Refusal", record["failure"]["kind"]),
                ("Reason", record["failure"]["message"]),
            ],
        )
        document.add(
            "<p>No accepted partial values or recommendation losses "
            "are retained.</p></section>"
        )
        return
    evaluation = record["evaluation"]
    work_facts = (
        _work_facts(evaluation["work"])
        if record["schema_version"] == 2
        else [("Total complete leaves", evaluation["total_leaves"])]
    )
    inspection._facts(
        document,
        [
            ("Exact best-action tie set", evaluation["best_actions"]),
            *work_facts,
            ("Reported numerical elapsed seconds", evaluation["elapsed_seconds"]),
            ("Comparison eligibility", record["diagnostics"]["comparison_eligibility"]),
        ],
    )
    labels = {
        _identity(row): row["label"]
        for row in record["decision_report"]["legal_actions"]
    }
    for index, row in enumerate(evaluation["actions"]):
        document.add(
            f'<article id="{prefix}action-{index}"><h3>Physical choice '
            + str(index)
            + ": "
            + escape(labels[_identity(row["action"])])
            + "</h3>"
        )
        exact = row["expected_value"]
        document.add(
            '<p class="exact-value"><strong>Exact expected shaped '
            "value:</strong> "
            "<code>" + exact["numerator"] + " / " + exact["denominator"] + "</code></p>"
        )
        inspection._facts(
            document,
            [
                ("Physical indices", row["action"]),
                ("Displayed decimal", row["expected_value_float"]),
                *(
                    _work_facts(row["work"])
                    if record["schema_version"] == 2
                    else [("Complete leaves", row["leaves"])]
                ),
                ("Terminal win mass", row["win_mass"]),
                ("Terminal loss mass", row["loss_mass"]),
                ("Ongoing mass", row["ongoing_mass"]),
            ],
        )
        document.add("</article>")
    pointer = "/" + (prefix[:-1] + "/" if prefix else "") + "evaluation"
    inspection._fragment(
        document,
        evaluation,
        pointer,
        "Complete stored action values and exact fractions",
    )
    document.add("</section>")


def _work_facts(work: dict) -> list[tuple[str, Any]]:
    return [
        ("Executed integer contribution updates", work["contributions"]),
        ("Executed binary64 payoff evaluations", work["payoff_evaluations"]),
        ("Largest stored damage-sum support", work["peak_bins"]),
        ("Represented physical damage tuples", work["represented_damage_combinations"]),
        (
            "Represented positive physical trace leaves",
            work["represented_trace_leaves"],
        ),
    ]


def _choices(document: inspection._Document, record: dict, *, prefix: str) -> None:
    document.add(f'<section id="{prefix}choices"><h2>Saved choice and value loss</h2>')
    if record["status"] == "refused":
        document.add(
            "<p>The reference refused. No quality comparison is "
            "available.</p></section>"
        )
        return
    diagnostics = record["diagnostics"]
    if diagnostics["recommendation"] is None:
        document.add(
            "<p>The saved decision requested no work and has no "
            "recommendation to price.</p>"
        )
    else:
        inspection._facts(
            document, [("Saved recommendation", diagnostics["recommendation"])]
        )
    if record["decision_report"]["schema_version"] == 3:
        document.add(
            "<p>The saved schema 3 decision declares root-specific sampling and "
            "survivor-first selection. Its recommendation is priced here. "
            "Ordinary encounter-order selectors do not describe that treatment "
            "and are not substituted or guessed.</p>"
        )
        inspection._facts(document, [
            ("Saved sampling policy",
             record["decision_report"]["configuration"]["sampling_policy"]),
            ("Saved final treatment",
             record["decision_report"]["configuration"]["final_action_rule"]),
        ])
    elif diagnostics["same_statistics"] is None:
        document.add(
            "<p>Version 1 did not retain encounter ties. Alternate "
            "selectors are unavailable rather than guessed.</p>"
        )
    else:
        document.add(
            "<p>Both selectors use the same saved root statistics and "
            "encounter order without search. Their exact one-round "
            "losses refer to this state and objective only.</p>"
        )
        inspection._facts(document, list(diagnostics["same_statistics"].items()))
    pointer = "/" + (prefix[:-1] + "/" if prefix else "") + "diagnostics"
    inspection._fragment(
        document,
        diagnostics,
        pointer,
        "Complete derived choices, eligibility and exact losses",
    )
    document.add("</section>")


def reference_inspection_html(path: Path, appearance: str = "obscur") -> bytes:
    """Read one complete or refused saved report as self-contained passive HTML."""
    _appearance(appearance)
    record, captured = _capture(path, "reference report")
    if record["format"] != FORMAT:
        from .adaptive_report import render_inspection

        return render_inspection(record, captured, appearance)
    document = _start("One-round reference inspection", appearance)
    document.add(
        '<header id="overview"><h1>One-round reference inspection</h1>'
        "<p>Read the saved model and limits before interpreting its "
        "values. No calculation, environment replay or search runs "
        "during inspection.</p></header>"
    )
    inspection._facts(
        document,
        [
            ("Captured report bytes", len(captured)),
            ("Captured report SHA-256", hashlib.sha256(captured).hexdigest()),
            ("Screen edition", appearance),
        ],
    )
    document.add(
        '<nav aria-label="Report sections">'
        '<a href="#meaning">Model and limits</a>'
        '<a href="#state">Saved state</a><a href="#values">Action values</a>'
        '<a href="#choices">Choices and losses</a>'
        '<a href="#provenance">Source and producer</a></nav>'
    )
    _meaning(document, record, prefix="")
    document.add('<section id="state"><h2>Selected saved pre-action state</h2>')
    inspection._facts(
        document,
        [
            ("Exact state SHA-256", record["selected_state_sha256"]),
            ("Selection", record["decision_report"]["selection"]),
        ],
    )
    inspection._boundary(document, record["decision_report"]["selected_state"])
    inspection._fragment(
        document,
        record["decision_report"]["selected_state"],
        "/decision_report/selected_state",
        "Complete exact saved state",
    )
    document.add("</section>")
    _values(document, record, prefix="")
    _choices(document, record, prefix="")
    document.add(
        '<section id="provenance"><h2>Source report and producer identities</h2>'
    )
    for name in (
        "source_report",
        "identity_comparisons",
        "implementation",
        "reference_engine_files_sha256",
        "decision_report",
    ):
        inspection._fragment(
            document, record[name], "/" + name, "Complete " + name.replace("_", " ")
        )
    document.add("</section>")
    return _finish(document)


def _pair_eligibility(left: dict, right: dict) -> list[str]:
    reasons = []
    if left["status"] != "complete" or right["status"] != "complete":
        reasons.append("one_or_both_reports_refused")
    if not _same(
        left["decision_report"]["selected_state"],
        right["decision_report"]["selected_state"],
    ):
        reasons.append("exact_saved_states_differ")
    for name in (
        "model",
        "horizon_rounds",
        "terminal_depth",
        "probability_model",
        "value_model",
    ):
        if not _same(left[name], right[name]):
            reasons.append(name + "_differs")
    if not reasons:
        for side, report in (("left", left), ("right", right)):
            if not report["diagnostics"]["comparison_eligibility"]["eligible"]:
                reasons.append(side + "_search_objective_or_engine_differs")
        left_values = [
            (row["action"], row["expected_value"])
            for row in left["evaluation"]["actions"]
        ]
        right_values = [
            (row["action"], row["expected_value"])
            for row in right["evaluation"]["actions"]
        ]
        if not _same(left_values, right_values):
            reasons.append("reported_reference_values_disagree")
    return reasons


def reference_comparison_html(
    left: Path, right: Path, appearance: str = "obscur"
) -> bytes:
    """Compare saved reports without ranking incompatible declared objectives."""
    _appearance(appearance)
    left_report, left_bytes = _capture(left, "left reference report")
    right_report, right_bytes = _capture(right, "right reference report")
    if left_report["format"] != FORMAT or right_report["format"] != FORMAT:
        from .adaptive_report import render_comparison

        return render_comparison(
            left_report, left_bytes, right_report, right_bytes, appearance
        )
    inspection._pair_values(left_report, right_report)
    reasons = _pair_eligibility(left_report, right_report)
    document = _start("One-round reference comparison", appearance)
    document.add(
        '<header id="overview"><h1>One-round reference comparison</h1>'
        "<p>Saved reports are read without search or reference "
        "recomputation. Exact state, model and objective come before "
        "reported value losses.</p></header>"
    )
    inspection._facts(
        document,
        [
            ("Left captured SHA-256", hashlib.sha256(left_bytes).hexdigest()),
            ("Right captured SHA-256", hashlib.sha256(right_bytes).hexdigest()),
            ("Comparison eligible", not reasons),
            ("Remaining boundaries", reasons),
            ("Left computation method", _computation_method(left_report)),
            ("Right computation method", _computation_method(right_report)),
            (
                "Producer identities equal",
                _same(left_report["implementation"], right_report["implementation"]),
            ),
            (
                "Operational limits equal",
                _same(left_report["limits"], right_report["limits"]),
            ),
        ],
    )
    document.add(
        '<nav aria-label="Comparison sections">'
        '<a href="#comparison">Comparison</a>'
        '<a href="#left-meaning">Left model and limits</a>'
        '<a href="#left-values">Left values</a>'
        '<a href="#right-meaning">Right model and limits</a>'
        '<a href="#right-values">Right values</a></nav>'
        '<section id="comparison"><h2>One-round value loss comparison</h2>'
    )
    if _computation_method(left_report) != _computation_method(right_report):
        document.add(
            "<p>The computation methods and work units differ. That difference "
            "does not change the declared mathematical model. Eligibility still "
            "requires equal exact states, law, objective and complete saved values. "
            "The work counters do not establish a measured performance ratio.</p>"
        )
    if reasons:
        document.add(
            "<p>These reports are ineligible for a common quality ranking. "
            "No winner is declared. The exact boundary reasons are "
            "shown above.</p>"
        )
    else:
        choices = [
            report["diagnostics"]["recommendation"]
            for report in (left_report, right_report)
        ]
        if any(choice is None for choice in choices):
            document.add(
                "<p>One or both saved decisions have no recommendation. "
                "Their complete reference values can be compared, but "
                "no selected-action quality ranking is available.</p>"
            )
        else:
            losses = [
                _fraction(choice["value_loss"], "/diagnostics/value_loss")
                for choice in choices
            ]
            description = (
                "The saved choices have equal exact one-round value loss."
                if losses[0] == losses[1]
                else "The left saved choice has lower exact one-round value loss."
                if losses[0] < losses[1]
                else "The right saved choice has lower exact one-round value loss."
            )
            document.add(
                "<p>" + description + " This conclusion applies to the "
                "shared state and declared objective only.</p>"
            )
            inspection._facts(
                document,
                [
                    ("Left choice and loss", choices[0]),
                    ("Right choice and loss", choices[1]),
                ],
            )
    document.add("</section>")
    for side, report in (("left", left_report), ("right", right_report)):
        _meaning(document, report, prefix=side + "-")
        _values(document, report, prefix=side + "-")
        _choices(document, report, prefix=side + "-")
        document.add(
            f'<section id="{side}-provenance"><h2>{side.title()} source '
            "and producer</h2>"
        )
        for name in (
            "selected_state_sha256",
            "source_report",
            "implementation",
            "reference_engine_files_sha256",
            "identity_comparisons",
            "decision_report",
        ):
            inspection._fragment(
                document,
                report[name],
                "/" + side + "/" + name,
                "Complete " + side + " " + name.replace("_", " "),
            )
        document.add("</section>")
    return _finish(document)
