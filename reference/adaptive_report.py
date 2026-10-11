"""Passive admission and reading of the separately named adaptive report.

The reader checks stored arithmetic, physical copies and work consistency. It
does not calculate successor distributions, replay the engine or authenticate
the supplied report. The numerical producer remains a separate dependency.
"""

from __future__ import annotations

import copy
import hashlib
from fractions import Fraction
from html import escape
from typing import Any

from game import episode_inspection as inspection
from game import episode_record as records

from . import report as legacy

FORMAT = "mcts-two-round-adaptive-reference-report"
MODEL = "independent_two_round_adaptive_binary53_shaped_v1"
METHOD = "adaptive-physical"
PROBABILITY_MODEL = "iid_binary53_inclusive_integer_v1"
VALUE_MODEL = "source_order_binary64_shaped_depth_two_v1"
ACTION_SEMANTICS = "physical_current_hand_index_and_original_root_copy_v1"
OBSERVATION_KEY = (
    "complete normalized post-round state with type-tagged numeric values, "
    "ordered physical hand and original root hand indices; no draw tape"
)
MASS_KEYS = ("win_depth_1", "loss_depth_1", "win_depth_2", "loss_depth_2", "cutoff")
MAX_TRANSITIONS = 1_000_000
MAX_PER_ACTION = 250_000
MAX_WORK_UNITS = 3_000_000
MAX_SECONDS = 30.0
BASE_FIELDS = {
    "format",
    "schema_version",
    "source_report",
    "decision_report",
    "selected_state",
    "selected_state_sha256",
    "implementation",
    "identity_comparisons",
    "model",
    "horizon_rounds",
    "terminal_depth",
    "probability_model",
    "value_model",
    "action_semantics",
    "computation_method",
    "limits",
    "new_search_performed",
    "reference_engine_files_sha256",
}
EVALUATION_FIELDS = {
    "model",
    "horizon_rounds",
    "probability_model",
    "value_model",
    "actions",
    "optimal_actions",
    "best_value",
    "source_provenance",
    "observation_key",
    "work",
}
WORK_COUNTERS = {
    "first_round_transitions",
    "second_round_transitions",
    "transition_leaves",
    "payoff_evaluations",
    "observation_group_operations",
    "cache_hits",
    "cache_misses",
    "work_units",
}
CACHE_POLICY = "request_local_complete_continuation_on_miss"
WORK_UNIT_RULE = "transition_leaves + payoff_evaluations + observation_group_operations"
_fraction = legacy._fraction
_fraction_object = legacy._fraction_object
_same = legacy._same


def _model(obj: dict, location: str = "") -> None:
    for name, expected in (
        ("model", MODEL),
        ("probability_model", PROBABILITY_MODEL),
        ("value_model", VALUE_MODEL),
    ):
        records._choice(obj[name], location + "/" + name, {expected})
    records.integer(obj["horizon_rounds"], location + "/horizon_rounds", 2, 2)


def _limits(value: Any) -> dict:
    obj = records._object(
        value,
        "/limits",
        {
            "max_transitions",
            "max_per_action",
            "max_work_units",
            "max_seconds",
        },
    )
    for name, ceiling in (
        ("max_transitions", MAX_TRANSITIONS),
        ("max_per_action", MAX_PER_ACTION),
        ("max_work_units", MAX_WORK_UNITS),
    ):
        records.integer(obj[name], "/limits/" + name, 1, ceiling)
    records._number(obj["max_seconds"], "/limits/max_seconds", 0, MAX_SECONDS)
    if obj["max_seconds"] == 0:
        records._error("/limits/max_seconds", "require a finite positive deadline")
    return obj


def _plain_card(
    value: Any, location: str, *, attack: bool = False, narrow: bool = True
) -> None:
    records._card(value, location)
    legacy._qualified_card(value, location)
    records._choice(
        value["card_type"],
        location + "/card_type",
        {"damage"} if attack else {"damage", "heal"},
    )
    if any(value[name] != 0 for name in ("modifier", "dot_tick", "dot_rounds")):
        records._error(location, "plain cards exclude effects")
    if value["card_type"] == "damage":
        if value["heal"] != 0:
            records._error(location + "/heal", "damage excludes drain payloads")
        if narrow and value["damage_max"] - value["damage_min"] + 1 > 3:
            records._error(location, "require at most three damage integers")
    elif (
        value["damage_min"] != 0
        or value["damage_max"] != 0
        or value["hits_all"] is not False
    ):
        records._error(location, "pure healing excludes damage and area payloads")


def _plain_fighter(value: Any, location: str, *, enemy: bool, root: bool) -> None:
    records._combatant(value, location)
    records.integer(value["hp"], location + "/hp", 1 if root else 0, value["max_hp"])
    for name in ("pips", "power_pips"):
        records.integer(value[name], location + "/" + name, 0, 7)
    if value["pips"] + value["power_pips"] > 7:
        records._error(location, "at most seven resource slots are supported")
    for name in ("blades", "traps", "shields", "dots"):
        if value[name] != []:
            records._error(location + "/" + name, "effects are excluded")
    for name in ("resist", "boost"):
        if set(value[name]) - legacy.ELEMENTS:
            records._error(location + "/" + name, "unknown element key")
        for element, amount in value[name].items():
            records._number(amount, location + "/" + name + "/" + element, 0, 0)
    if value["is_boss"] is not False or value["policy"] is not None:
        records._error(location, "boss flags and policies are excluded")
    attack = value["base_attack"]
    if enemy and attack is None:
        records._error(
            location + "/base_attack", "an explicit narrow attack is required"
        )
    if attack is not None:
        _plain_card(attack, location + "/base_attack", attack=True, narrow=enemy)


def qualified_state(
    value: Any, location: str = "/selected_state", *, root: bool = True
) -> dict:
    """Admit the named subset without importing the numerical reference."""
    obj = records._object(
        value, location, {"player", "enemies", "hand", "round_num", "boss_rules"}
    )
    records.integer(obj["round_num"], location + "/round_num", 1, 30 if root else 31)
    if obj["boss_rules"] != []:
        records._error(location + "/boss_rules", "rules are excluded")
    _plain_fighter(obj["player"], location + "/player", enemy=False, root=root)
    enemies = records._array(obj["enemies"], location + "/enemies", 1, 1)
    _plain_fighter(enemies[0], location + "/enemies/0", enemy=True, root=root)
    for index, card in enumerate(records._array(obj["hand"], location + "/hand", 0, 3)):
        _plain_card(card, f"{location}/hand/{index}")
    return obj


def _actions(state: dict) -> list[dict]:
    return legacy._physical_actions(state)


def qualify_decision(decision: dict) -> None:
    qualified_state(decision["selected_state"], "/decision_report/selected_state")
    expected = _actions(decision["selected_state"])
    actual = [
        {name: row[name] for name in ("card_idx", "target_idx")}
        for row in decision["legal_actions"]
    ]
    if not _same(expected, actual):
        records._error(
            "/decision_report/legal_actions",
            "require every legal physical action in source order",
        )


def _comparisons(decision: dict | None, implementation: dict) -> dict:
    if decision is not None:
        return legacy._comparisons(decision, implementation)
    return {
        "search_engine_files_equal": None,
        "search_producer_equal": None,
        "entrypoint_roles": {
            "search": None,
            "reference": "reference_episode.py",
            "same_role": False,
        },
    }


def _validate_base(value: Any, *, envelope: bool = True) -> dict:
    if envelope:
        records._envelope(value, 250_000, 10**300)
    obj = records._object(value, "/report", BASE_FIELDS)
    records._choice(obj["format"], "/format", {FORMAT})
    records.integer(obj["schema_version"], "/schema_version", 1, 1)
    _model(obj)
    records.integer(obj["terminal_depth"], "/terminal_depth", 2, 2)
    records._choice(obj["computation_method"], "/computation_method", {METHOD})
    records._choice(obj["action_semantics"], "/action_semantics", {ACTION_SEMANTICS})
    _limits(obj["limits"])
    if obj["new_search_performed"] is not False:
        records._error("/new_search_performed", "the reference runs no search")
    if not legacy.qualified_engine_files(obj["reference_engine_files_sha256"]):
        records._error(
            "/reference_engine_files_sha256",
            "require a qualified engine hash map",
        )
    source = records._object(
        obj["source_report"],
        "/source_report",
        {
            "kind",
            "bytes",
            "sha256",
            "canonical_sha256",
        },
    )
    records._choice(
        source["kind"], "/source_report/kind", {"saved-decision", "normalized-state"}
    )
    records.integer(source["bytes"], "/source_report/bytes", 1, records.RECORD_BYTES)
    for name in ("sha256", "canonical_sha256"):
        records._digest(source[name], "/source_report/" + name)
    records._state(obj["selected_state"], "/selected_state")
    decision = obj["decision_report"]
    if source["kind"] == "saved-decision":
        decision = inspection.validate_decision_report(decision)
        legacy._saved_identity_comparisons(decision)
        if not _same(obj["selected_state"], decision["selected_state"]):
            records._error(
                "/selected_state", "must retain the exact nested saved state"
            )
        canonical_source = decision
    else:
        if decision is not None:
            records._error(
                "/decision_report", "normalized state input has no saved decision"
            )
        canonical_source = obj["selected_state"]
    if (
        source["canonical_sha256"]
        != hashlib.sha256(records.canonical(canonical_source)).hexdigest()
    ):
        records._error(
            "/source_report/canonical_sha256",
            "must bind the complete source representation",
        )
    records._digest(obj["selected_state_sha256"], "/selected_state_sha256")
    if (
        obj["selected_state_sha256"]
        != hashlib.sha256(records.canonical(obj["selected_state"])).hexdigest()
    ):
        records._error("/selected_state_sha256", "must bind the exact selected state")
    implementation = legacy._implementation(obj["implementation"])
    if not {"reference/adaptive.py", "reference/adaptive_report.py"} <= set(
        implementation["reference_files_sha256"]
    ):
        records._error(
            "/implementation/reference_files_sha256",
            "require the adaptive calculation and reader identities",
        )
    if not _same(obj["identity_comparisons"], _comparisons(decision, implementation)):
        records._error(
            "/identity_comparisons", "must derive the saved producer comparisons"
        )
    return obj


def reference_report_base(
    source: dict,
    captured: bytes,
    implementation: dict,
    limits: dict,
    *,
    state_input: bool = False,
) -> dict:
    """Bind one captured input and its already admitted representation."""
    if (
        not isinstance(captured, bytes)
        or not 1 <= len(captured) <= records.RECORD_BYTES
    ):
        records._error("source input", "require bounded nonempty captured bytes")
    decision = None if state_input else source
    state = source if state_input else source["selected_state"]
    observed_engine = implementation["decision_consumer"]["engine_files_sha256"]
    qualified_engine = (
        observed_engine
        if legacy.qualified_engine_files(observed_engine)
        else legacy.REFERENCE_ENGINE_FILES_SHA256
    )
    base = {
        "format": FORMAT,
        "schema_version": 1,
        "source_report": {
            "kind": "normalized-state" if state_input else "saved-decision",
            "bytes": len(captured),
            "sha256": hashlib.sha256(captured).hexdigest(),
            "canonical_sha256": hashlib.sha256(records.canonical(source)).hexdigest(),
        },
        "decision_report": copy.deepcopy(decision),
        "selected_state": copy.deepcopy(state),
        "selected_state_sha256": hashlib.sha256(records.canonical(state)).hexdigest(),
        "implementation": copy.deepcopy(implementation),
        "identity_comparisons": _comparisons(decision, implementation),
        "model": MODEL,
        "horizon_rounds": 2,
        "terminal_depth": 2,
        "probability_model": PROBABILITY_MODEL,
        "value_model": VALUE_MODEL,
        "action_semantics": ACTION_SEMANTICS,
        "computation_method": METHOD,
        "limits": copy.deepcopy(limits),
        "new_search_performed": False,
        "reference_engine_files_sha256": copy.deepcopy(qualified_engine),
    }
    return _validate_base(base)


def _probability(value: Any, location: str, *, rounds: int = 1) -> Fraction:
    result = _fraction(value, location, probability=True)
    # At most five binary53 tests and two width-three damage draws per round.
    if ((1 << (265 * rounds)) * (9**rounds)) % result.denominator:
        records._error(location, "denominator is outside the declared draw support")
    return result


def _masses(value: Any, location: str, *, rounds: int) -> list[Fraction]:
    obj = records._object(value, location, set(MASS_KEYS))
    masses = [
        _probability(obj[name], location + "/" + name, rounds=rounds)
        for name in MASS_KEYS
    ]
    if sum(masses, Fraction(0)) != 1:
        records._error(location, "all five outcome masses must sum to exactly one")
    return masses


def _value(value: Any, location: str, masses: list[Fraction] | None = None) -> Fraction:
    result = _fraction(value, location, probability=True)
    if masses is not None:
        atoms = (1.0 - 0.045, 0.15 * (1 / 2), 1.0 - 0.045 * 2, 0.15 * (2 / 2))
        terminal_value = sum(
            (
                Fraction.from_float(atom) * mass
                for atom, mass in zip(atoms, masses[:4], strict=True)
            ),
            Fraction(0),
        )
        if not terminal_value <= result <= terminal_value + masses[4]:
            records._error(
                location,
                "must respect the exact depth-specific atoms and cutoff bounds",
            )
    return result


def _indices(value: Any, location: str, expected: list[int]) -> None:
    actual = records._array(value, location, 0, 4)
    for index, number in enumerate(actual):
        records.integer(number, f"{location}/{index}", 0, 3)
    if not _same(actual, expected):
        records._error(location, "must retain every exact tie in offered action order")


def _terminal(state: dict) -> str | None:
    return (
        "loss"
        if state["player"]["hp"] == 0
        else "win"
        if state["enemies"][0]["hp"] == 0
        else None
    )


def _observation_state(
    state: Any, root: dict, retained: list[int], location: str
) -> dict:
    obj = qualified_state(state, location, root=False)
    if obj["round_num"] != root["round_num"] + 1:
        records._error(
            location + "/round_num", "must advance exactly one observed round"
        )
    if not _same(obj["hand"], [root["hand"][index] for index in retained]):
        records._error(
            location + "/hand",
            "must retain the ordered physical copies after the first action",
        )
    for old, current, path in (
        (root["player"], obj["player"], "/player"),
        (root["enemies"][0], obj["enemies"][0], "/enemies/0"),
    ):
        unchanged = set(old) - {"hp", "pips", "power_pips"}
        if not _same(
            {name: old[name] for name in unchanged},
            {name: current[name] for name in unchanged},
        ):
            records._error(
                location + path,
                "must retain every static normalized field and literal value",
            )
    return obj


def _success_sides(accuracy: int | float) -> tuple[bool, bool]:
    numerator, denominator = float(accuracy).as_integer_ratio()
    count = min(1 << 53, (numerator * (1 << 53)) // denominator + 1)
    return count > 0, count < 1 << 53


def _slots_after_payment(fighter: dict, card: dict | None) -> int:
    normal, power = fighter["pips"], fighter["power_pips"]
    if card is not None:
        multiplier = 2 if fighter["element"] == card["element"] else 1
        consumed = min(power, (card["pip_cost"] + multiplier - 1) // multiplier)
        power -= consumed
        normal = max(0, normal - max(0, card["pip_cost"] - consumed * multiplier))
    return normal + power


def _regen_sides(fighter: dict, slots: int) -> int:
    return 1 if slots >= 7 or fighter["power_pip_chance"] in (0, 1) else 2


def _round_leaf_support(state: dict, action: dict) -> int:
    """Count positive trace support only, without successor or payoff production.

    These narrow cards carry no effects. Player regeneration is unconditional.
    Enemy HP controls response and regeneration support, while an enemy's cast
    branches share the same resource payment even when the player dies.
    """
    player, enemy = state["player"], state["enemies"][0]
    card = None if action["card_idx"] is None else state["hand"][action["card_idx"]]
    player_regen = _regen_sides(player, _slots_after_payment(player, card))
    enemy_hp_support = [enemy["hp"]]
    if card is not None:
        success, fizzle = _success_sides(card["accuracy"])
        enemy_hp_support = [enemy["hp"]] if fizzle else []
        if success:
            if card["card_type"] == "damage":
                enemy_hp_support.extend(
                    max(0, enemy["hp"] - damage)
                    for damage in range(card["damage_min"], card["damage_max"] + 1)
                )
            else:
                enemy_hp_support.append(enemy["hp"])
    attack = enemy["base_attack"]
    multiplier = 2 if attack["element"] == enemy["element"] else 1
    affordable = enemy["pips"] + multiplier * enemy["power_pips"] >= attack["pip_cost"]
    before = _regen_sides(enemy, _slots_after_payment(enemy, None))
    after = _regen_sides(enemy, _slots_after_payment(enemy, attack))
    success, fizzle = _success_sides(attack["accuracy"])
    casts = (attack["damage_max"] - attack["damage_min"] + 1 if success else 0) + int(
        fizzle
    )
    total = 0
    for hp in enemy_hp_support:
        response_support = (
            1 if hp == 0 else before if not affordable else before + casts * after
        )
        total += player_regen * response_support
    return total


def _work(value: Any, limits: dict, expected: dict) -> None:
    obj = records._object(
        value,
        "/evaluation/work",
        WORK_COUNTERS
        | {
            "per_action_transition_leaves",
            "elapsed_seconds",
            "cache_policy",
            "work_unit_rule",
            "max_transitions",
            "max_per_action",
            "max_work_units",
            "max_seconds",
        },
    )
    for name in WORK_COUNTERS:
        records.integer(obj[name], "/evaluation/work/" + name, 0, MAX_WORK_UNITS)
        if obj[name] != expected[name]:
            records._error(
                "/evaluation/work/" + name,
                "must match the declared complete trace support "
                "and request-local accounting",
            )
    per_action = records._array(
        obj["per_action_transition_leaves"],
        "/evaluation/work/per_action_transition_leaves",
        1,
        4,
    )
    for index, amount in enumerate(per_action):
        records.integer(
            amount,
            f"/evaluation/work/per_action_transition_leaves/{index}",
            1,
            limits["max_per_action"],
        )
    if not _same(per_action, expected["per_action_transition_leaves"]):
        records._error(
            "/evaluation/work/per_action_transition_leaves",
            "must charge each executed continuation miss "
            "to its first owning root action",
        )
    for name in limits:
        if not _same(obj[name], limits[name]):
            records._error(
                "/evaluation/work/" + name, "must retain the report's exact control"
            )
    if (
        obj["transition_leaves"] > limits["max_transitions"]
        or obj["work_units"] > limits["max_work_units"]
    ):
        records._error("/evaluation/work", "completed work exceeds its declared cap")
    records._number(
        obj["elapsed_seconds"],
        "/evaluation/work/elapsed_seconds",
        0,
        limits["max_seconds"],
    )
    if obj["elapsed_seconds"] >= limits["max_seconds"]:
        records._error(
            "/evaluation/work/elapsed_seconds",
            "complete assembly must precede the cooperative deadline",
        )
    records._choice(
        obj["cache_policy"], "/evaluation/work/cache_policy", {CACHE_POLICY}
    )
    records._choice(
        obj["work_unit_rule"], "/evaluation/work/work_unit_rule", {WORK_UNIT_RULE}
    )


def _evaluation(value: Any, base: dict) -> dict:
    obj = records._object(value, "/evaluation", EVALUATION_FIELDS)
    _model(obj, "/evaluation")
    records._choice(
        obj["observation_key"], "/evaluation/observation_key", {OBSERVATION_KEY}
    )
    if not _same(
        obj["source_provenance"],
        {"transition_helper": "reference/one_round.py", "qualification_model": MODEL},
    ):
        records._error(
            "/evaluation/source_provenance",
            "must identify the declared installed helper adaptation",
        )
    root = qualified_state(base["selected_state"])
    decision = base["decision_report"]
    if decision is not None:
        if decision["configuration"]["horizon_rounds"] != 2:
            records._error(
                "/decision_report/configuration/horizon_rounds",
                "complete adaptive pricing requires horizon two",
            )
        qualify_decision(decision)
    expected_actions = _actions(root)
    rows = records._array(obj["actions"], "/evaluation/actions", 1, 4)
    if len(rows) != len(expected_actions):
        records._error(
            "/evaluation/actions", "must retain the complete legal first-action set"
        )
    values = []
    work = dict.fromkeys(WORK_COUNTERS, 0)
    work["per_action_transition_leaves"] = []
    cache = {}
    for index, row in enumerate(rows):
        path = f"/evaluation/actions/{index}"
        row = records._object(
            row,
            path,
            {"action", "value", "total_probability", "masses", "observations"},
        )
        legacy._action(row["action"], path + "/action")
        if not _same(row["action"], expected_actions[index]):
            records._error(
                path + "/action",
                "must retain the offered physical first action at this index",
            )
        if _probability(row["total_probability"], path + "/total_probability") != 1:
            records._error(path, "complete first-action probability must be one")
        first_leaves = _round_leaf_support(root, row["action"])
        root_leaves = first_leaves
        work["first_round_transitions"] += first_leaves
        retained = list(range(len(root["hand"])))
        if row["action"]["card_idx"] is not None:
            retained.pop(row["action"]["card_idx"])
        probability = Fraction(0)
        reconstructed_value = Fraction(0)
        reconstructed_masses = [Fraction(0) for _ in MASS_KEYS]
        observations = records._array(
            row["observations"], path + "/observations", 1, 80
        )
        if len(observations) > first_leaves:
            records._error(
                path + "/observations",
                "distinct positive observations cannot exceed "
                "positive first-round trace leaves",
            )
        observed_keys = set()
        work["observation_group_operations"] += first_leaves + len(observations)
        for observed_index, observation in enumerate(observations):
            op = f"{path}/observations/{observed_index}"
            observation = records._object(
                observation,
                op,
                {
                    "state",
                    "root_hand_indices",
                    "probability",
                    "terminal",
                    "continuations",
                    "optimal_actions",
                    "chosen",
                    "adaptive_value",
                },
            )
            mapping = records._array(
                observation["root_hand_indices"], op + "/root_hand_indices", 0, 3
            )
            for copy_index, number in enumerate(mapping):
                records.integer(number, f"{op}/root_hand_indices/{copy_index}", 0, 2)
            if not _same(mapping, retained):
                records._error(
                    op + "/root_hand_indices",
                    "must retain original root copy indices in remaining hand order",
                )
            observed = _observation_state(
                observation["state"], root, retained, op + "/state"
            )
            key = records.canonical({"state": observed, "root_hand_indices": mapping})
            if key in observed_keys:
                records._error(
                    op,
                    "equal complete observations and copy mappings "
                    "must be grouped once",
                )
            observed_keys.add(key)
            mass = _probability(observation["probability"], op + "/probability")
            if mass == 0:
                records._error(
                    op + "/probability",
                    "every retained observation requires positive mass",
                )
            probability += mass
            terminal = _terminal(observed)
            if observation["terminal"] != terminal:
                records._error(
                    op + "/terminal",
                    "must match observed HP with player-death priority",
                )
            alternatives = records._array(
                observation["continuations"], op + "/continuations", 0, 4
            )
            if terminal is not None:
                if (
                    alternatives
                    or observation["optimal_actions"] != []
                    or observation["chosen"] is not None
                ):
                    records._error(
                        op,
                        "terminal observations have no second action, "
                        "tie or chosen index",
                    )
                adaptive = Fraction.from_float(
                    0.15 * (1 / 2) if terminal == "loss" else 1.0 - 0.045
                )
                conditional_masses = [Fraction(0) for _ in MASS_KEYS]
                conditional_masses[1 if terminal == "loss" else 0] = Fraction(1)
                work["payoff_evaluations"] += 1
            else:
                legal = _actions(observed)
                if len(alternatives) != len(legal):
                    records._error(
                        op + "/continuations", "must price every legal second action"
                    )
                conditional_values, offered_masses = [], []
                for alternative_index, continuation in enumerate(alternatives):
                    cp = f"{op}/continuations/{alternative_index}"
                    continuation = records._object(
                        continuation,
                        cp,
                        {
                            "action",
                            "root_card_idx",
                            "value",
                            "total_probability",
                            "masses",
                        },
                    )
                    legacy._action(continuation["action"], cp + "/action")
                    if not _same(continuation["action"], legal[alternative_index]):
                        records._error(
                            cp + "/action",
                            "must retain complete legal second actions "
                            "in current hand order",
                        )
                    local = continuation["action"]["card_idx"]
                    original = None if local is None else retained[local]
                    if continuation["root_card_idx"] is not None:
                        records.integer(
                            continuation["root_card_idx"], cp + "/root_card_idx", 0, 2
                        )
                    if not _same(continuation["root_card_idx"], original):
                        records._error(
                            cp + "/root_card_idx",
                            "must map the current hand copy to its original root index",
                        )
                    if (
                        _probability(
                            continuation["total_probability"], cp + "/total_probability"
                        )
                        != 1
                    ):
                        records._error(
                            cp, "each complete continuation probability must be one"
                        )
                    cm = _masses(continuation["masses"], cp + "/masses", rounds=1)
                    if cm[0] or cm[1]:
                        records._error(
                            cp + "/masses",
                            "second-round alternatives have zero depth-one mass",
                        )
                    cv = _value(continuation["value"], cp + "/value", cm)
                    conditional_values.append(cv)
                    offered_masses.append(cm)
                    cache_key = (key, local, continuation["action"]["target_idx"])
                    arithmetic = (cv, tuple(cm))
                    if cache_key in cache:
                        if arithmetic != cache[cache_key]:
                            records._error(
                                cp,
                                "equal observed states and physical actions "
                                "require equal stored conditional arithmetic",
                            )
                        work["cache_hits"] += 1
                    else:
                        cache[cache_key] = arithmetic
                        work["cache_misses"] += 1
                        leaves = _round_leaf_support(observed, continuation["action"])
                        root_leaves += leaves
                        work["second_round_transitions"] += leaves
                        work["payoff_evaluations"] += leaves
                adaptive = max(conditional_values)
                ties = [
                    i
                    for i, conditional in enumerate(conditional_values)
                    if conditional == adaptive
                ]
                _indices(observation["optimal_actions"], op + "/optimal_actions", ties)
                records.integer(
                    observation["chosen"], op + "/chosen", 0, len(alternatives) - 1
                )
                if observation["chosen"] != ties[0]:
                    records._error(
                        op + "/chosen",
                        "the first exact tied continuation defines outcome masses",
                    )
                conditional_masses = offered_masses[ties[0]]
            if (
                _value(observation["adaptive_value"], op + "/adaptive_value")
                != adaptive
            ):
                records._error(
                    op + "/adaptive_value",
                    "must equal the terminal atom or exact maximum conditional value",
                )
            reconstructed_value += mass * adaptive
            for mass_index, conditional in enumerate(conditional_masses):
                reconstructed_masses[mass_index] += mass * conditional
        if probability != 1:
            records._error(
                path + "/observations",
                "complete first-observation probability must sum to exactly one",
            )
        masses = _masses(row["masses"], path + "/masses", rounds=2)
        if masses != reconstructed_masses:
            records._error(
                path + "/masses",
                "must weight terminal observations and first-tie continuation masses",
            )
        value = _value(row["value"], path + "/value", masses)
        if value != reconstructed_value:
            records._error(
                path + "/value",
                "must reconstruct the complete adaptive root expectation",
            )
        values.append(value)
        work["per_action_transition_leaves"].append(root_leaves)
    best = max(values)
    _indices(
        obj["optimal_actions"],
        "/evaluation/optimal_actions",
        [i for i, value in enumerate(values) if value == best],
    )
    if _value(obj["best_value"], "/evaluation/best_value") != best:
        records._error(
            "/evaluation/best_value", "must equal the exact best root expectation"
        )
    work["transition_leaves"] = (
        work["first_round_transitions"] + work["second_round_transitions"]
    )
    work["work_units"] = (
        work["transition_leaves"]
        + work["payoff_evaluations"]
        + work["observation_group_operations"]
    )
    _work(obj["work"], base["limits"], work)
    return obj


def _diagnostics(base: dict, evaluation: dict) -> dict:
    decision = base["decision_report"]
    if decision is None:
        return {
            "recommendation": None,
            "same_statistics": None,
            "comparison_eligibility": {"eligible": True, "reasons": []},
        }
    prices = {
        legacy._identity(row["action"]): _fraction(
            row["value"], "/evaluation/value", probability=True
        )
        for row in evaluation["actions"]
    }
    best = max(prices.values())

    def price(action: dict | None) -> dict | None:
        if action is None:
            return None
        identity = {name: action[name] for name in ("card_idx", "target_idx")}
        value = prices[legacy._identity(identity)]
        loss = best - value
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
            ranking = inspection.decision_ranking(decision, rule)
            selectors[rule] = price(ranking[0] if ranking else None)
    reasons = []
    if not base["identity_comparisons"]["search_engine_files_equal"]:
        reasons.append("search_engine_identity_differs")
    if decision["value_semantics"] != legacy.SEARCH_VALUE_SEMANTICS:
        reasons.append("search_value_declaration_differs")
    return {
        "recommendation": price(decision["recommendation"]),
        "same_statistics": selectors,
        "comparison_eligibility": {"eligible": not reasons, "reasons": reasons},
    }


def complete_reference_report(base: dict, evaluation: dict) -> dict:
    base = _validate_base(base)
    evaluation = _evaluation(evaluation, base)
    return validate_reference_report(
        {
            **copy.deepcopy(base),
            "status": "complete",
            "evaluation": copy.deepcopy(evaluation),
            "diagnostics": _diagnostics(base, evaluation),
            "failure": None,
        }
    )


def refused_reference_report(base: dict, kind: str, message: str) -> dict:
    base = _validate_base(base)
    return validate_reference_report(
        {
            **copy.deepcopy(base),
            "status": "refused",
            "evaluation": None,
            "diagnostics": None,
            "failure": {"kind": kind, "message": message},
        }
    )


def validate_reference_report(value: Any) -> dict:
    """Check saved consistency without importing or executing the evaluator."""
    records._envelope(value, 250_000, 10**300)
    obj = records._object(
        value,
        "/report",
        BASE_FIELDS | {"status", "evaluation", "diagnostics", "failure"},
    )
    base = _validate_base({name: obj[name] for name in BASE_FIELDS}, envelope=False)
    records._choice(obj["status"], "/status", {"complete", "refused"})
    if obj["status"] == "refused":
        if obj["evaluation"] is not None or obj["diagnostics"] is not None:
            records._error(
                "/evaluation", "refusal cannot retain accepted partial values"
            )
        failure = records._object(obj["failure"], "/failure", {"kind", "message"})
        records._choice(failure["kind"], "/failure/kind", legacy.REFUSAL_KINDS)
        records._string(failure["message"], "/failure/message", high=2048)
        if failure["kind"] == "engine_mismatch" and _same(
            obj["implementation"]["decision_consumer"]["engine_files_sha256"],
            obj["reference_engine_files_sha256"],
        ):
            records._error(
                "/failure/kind",
                "engine mismatch requires a different observed engine hash map",
            )
        if failure["kind"] == "horizon_mismatch" and (
            obj["decision_report"] is None
            or obj["decision_report"]["configuration"]["horizon_rounds"] == 2
        ):
            records._error(
                "/failure/kind",
                "horizon mismatch requires a saved decision with another horizon",
            )
    else:
        if obj["failure"] is not None:
            records._error("/failure", "complete reports require null")
        if not _same(
            obj["implementation"]["decision_consumer"]["engine_files_sha256"],
            obj["reference_engine_files_sha256"],
        ):
            records._error(
                "/implementation/decision_consumer/engine_files_sha256",
                "complete calculation requires its declared qualified engine bodies",
            )
        evaluation = _evaluation(obj["evaluation"], base)
        if not _same(obj["diagnostics"], _diagnostics(base, evaluation)):
            records._error(
                "/diagnostics",
                "must derive the saved choice and exact loss "
                "from complete adaptive values",
            )
    return obj


class _Document(inspection._Document):
    """Keep this report family's complete HTML inside the 8 MiB boundary."""

    def add(self, markup: str) -> None:
        if self.size + len(markup.encode("utf-8")) + 1 > records.RECORD_BYTES:
            raise inspection.InspectionRuntimeError(
                "generated adaptive HTML exceeds the 8 MiB output limit"
            )
        super().add(markup)


def _start(title: str, appearance: str) -> _Document:
    document = _Document()
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


def _meaning(document: inspection._Document, record: dict, *, prefix: str) -> None:
    document.add(
        f'<section id="{prefix}meaning"><h2>Adaptive model and limits</h2>'
        "<p>Fix the first physical action, observe the complete first-round "
        "state, then choose the legal second action with greatest exact "
        "conditional expectation. Every alternative and positive observation "
        "must complete. Outcome masses use the first offered action in an "
        "exact continuation tie.</p><p>Values are expected source-order "
        "binary64 shaped rewards under the declared independent draw law. "
        "They do not establish calibrated win probabilities, a full encounter "
        "optimum or stronger search play. Saved MCTS action-path means use "
        "a different averaging procedure.</p>"
    )
    inspection._facts(
        document,
        [
            ("Report status", record["status"]),
            ("Input kind", record["source_report"]["kind"]),
            ("Model", record["model"]),
            ("Computation method", record["computation_method"]),
            ("Probability law", record["probability_model"]),
            ("Value objective", record["value_model"]),
            ("Simulated round horizon", record["horizon_rounds"]),
            ("Maximum terminal depth", record["terminal_depth"]),
            ("Physical action semantics", record["action_semantics"]),
            ("New search performed", record["new_search_performed"]),
            ("Operational limits", record["limits"]),
        ],
    )
    document.add(
        "<p>The cooperative deadline is checked through complete numerical "
        "assembly. It supplies no hard external wall or memory guarantee. "
        "Every refusal omits accepted partial values. Passive reading checks "
        "stored arithmetic and consistency without recalculating successor "
        "distributions.</p></section>"
    )


def _values(document: inspection._Document, record: dict, *, prefix: str) -> None:
    document.add(f'<section id="{prefix}values"><h2>Complete adaptive root values</h2>')
    if record["status"] == "refused":
        inspection._facts(
            document,
            [
                ("Refusal", record["failure"]["kind"]),
                ("Reason", record["failure"]["message"]),
            ],
        )
        document.add(
            "<p>No accepted partial values or saved choice losses "
            "are retained.</p></section>"
        )
        return
    evaluation = record["evaluation"]
    inspection._facts(
        document,
        [
            ("Exact optimal root indices", evaluation["optimal_actions"]),
            ("Exact best value", evaluation["best_value"]),
            ("Executed work and request limits", evaluation["work"]),
        ],
    )
    decision = record["decision_report"]
    labels = (
        {}
        if decision is None
        else {legacy._identity(row): row["label"] for row in decision["legal_actions"]}
    )
    for index, row in enumerate(evaluation["actions"]):
        action = row["action"]
        card_index = action["card_idx"]
        label = labels.get(
            legacy._identity(action),
            "Pass"
            if card_index is None
            else record["selected_state"]["hand"][card_index]["name"],
        )
        document.add(
            f'<article id="{prefix}action-{index}"><h3>First physical choice {index}: '
            + escape(label, quote=True)
            + "</h3>"
        )
        exact = row["value"]
        document.add(
            '<p class="exact-value"><strong>Exact adaptive shaped value:'
            "</strong> <code>"
            + exact["numerator"]
            + " / "
            + exact["denominator"]
            + "</code></p>"
        )
        inspection._facts(
            document,
            [
                ("First action indices", action),
                ("Five depth-specific outcome masses", row["masses"]),
                ("Complete first observations", len(row["observations"])),
            ],
        )
        for observed_index, observation in enumerate(row["observations"]):
            document.add(
                f"<details><summary>Observation {observed_index}: second choice "
                + inspection._text(observation["chosen"])
                + "</summary>"
            )
            inspection._facts(
                document,
                [
                    ("Exact observation probability", observation["probability"]),
                    ("Observed terminal status", observation["terminal"]),
                    ("Observed player HP", observation["state"]["player"]["hp"]),
                    ("Observed enemy HP", observation["state"]["enemies"][0]["hp"]),
                    ("Original root hand copies", observation["root_hand_indices"]),
                    (
                        "Exact optimal continuation indices",
                        observation["optimal_actions"],
                    ),
                    ("Chosen first tie", observation["chosen"]),
                    ("Exact conditional adaptive value", observation["adaptive_value"]),
                ],
            )
            if observation["chosen"] is not None:
                inspection._facts(
                    document,
                    [
                        (
                            "Chosen physical continuation",
                            observation["continuations"][observation["chosen"]],
                        )
                    ],
                )
            document.add("</details>")
        document.add("</article>")
    pointer = "/" + (prefix[:-1] + "/" if prefix else "") + "evaluation"
    inspection._fragment(
        document,
        evaluation,
        pointer,
        "Complete stored observations, alternatives, fractions and work",
    )
    document.add("</section>")


def _choices(document: inspection._Document, record: dict, *, prefix: str) -> None:
    document.add(
        f'<section id="{prefix}choices"><h2>Saved root choice and exact value loss</h2>'
    )
    if record["status"] == "refused":
        document.add("<p>The reference refused. No selected action is priced.</p>")
    elif record["decision_report"] is None:
        document.add(
            "<p>This input is a supplied modeled state. It has no saved decision "
            "or selected recommendation. Complete adaptive values are available, "
            "while selected action loss remains null.</p>"
        )
    else:
        document.add(
            "<p>The saved root choice is priced under this adaptive objective. "
            "Its exact loss is the best complete root expectation minus that "
            "choice’s expectation. Saved search controls and action identities "
            "remain in the source decision.</p>"
        )
        inspection._facts(document, list(record["diagnostics"].items()))
    if record["status"] == "complete":
        pointer = "/" + (prefix[:-1] + "/" if prefix else "") + "diagnostics"
        inspection._fragment(
            document,
            record["diagnostics"],
            pointer,
            "Complete saved choice, selectors and exact losses",
        )
    document.add("</section>")


def _provenance(document: inspection._Document, record: dict, *, prefix: str) -> None:
    document.add(
        f'<section id="{prefix}provenance"><h2>Source and producer identities</h2>'
    )
    for name in (
        "source_report",
        "identity_comparisons",
        "implementation",
        "reference_engine_files_sha256",
        "selected_state",
        "decision_report",
    ):
        pointer = "/" + (prefix[:-1] + "/" if prefix else "") + name
        inspection._fragment(
            document, record[name], pointer, "Complete " + name.replace("_", " ")
        )
    document.add("</section>")


def render_inspection(record: dict, captured: bytes, appearance: str) -> bytes:
    document = _start("Two-round adaptive reference inspection", appearance)
    document.add(
        '<header id="overview"><h1>Two-round adaptive reference inspection</h1>'
        "<p>Passive inspection of stored data. Admission checks exact nested "
        "arithmetic and physical copy consistency. It does not authenticate "
        "origin, independently validate the supplied state or rerun the "
        "numerical reference.</p></header>"
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
        '<a href="#state">Supplied state</a>'
        '<a href="#values">Root values and observations</a>'
        '<a href="#choices">Saved choices and losses</a>'
        '<a href="#provenance">Source and producer</a></nav>'
    )
    _meaning(document, record, prefix="")
    document.add('<section id="state"><h2>Selected input state</h2>')
    inspection._facts(
        document,
        [
            ("Exact state SHA-256", record["selected_state_sha256"]),
            ("Input kind", record["source_report"]["kind"]),
        ],
    )
    inspection._boundary(document, record["selected_state"])
    document.add("</section>")
    _values(document, record, prefix="")
    _choices(document, record, prefix="")
    _provenance(document, record, prefix="")
    return legacy._finish(document)


def _pair_eligibility(left: dict, right: dict) -> list[str]:
    reasons = []
    if left["format"] != FORMAT or right["format"] != FORMAT:
        return ["reference_report_families_differ"]
    if left["status"] != "complete" or right["status"] != "complete":
        reasons.append("one_or_both_reports_refused")
    if not _same(left["selected_state"], right["selected_state"]):
        reasons.append("exact_saved_states_differ")
    for name in (
        "model",
        "horizon_rounds",
        "terminal_depth",
        "probability_model",
        "value_model",
        "action_semantics",
    ):
        if not _same(left[name], right[name]):
            reasons.append(name + "_differs")
    if not reasons:
        for side, report in (("left", left), ("right", right)):
            if not report["diagnostics"]["comparison_eligibility"]["eligible"]:
                reasons.append(side + "_search_objective_or_engine_differs")
        fields = ("actions", "optimal_actions", "best_value")
        # Work and elapsed time may differ with controls. Conditional arithmetic
        # and physical alternatives must still describe the same whole model.
        if not _same(
            {name: left["evaluation"][name] for name in fields},
            {name: right["evaluation"][name] for name in fields},
        ):
            reasons.append("reported_reference_values_disagree")
    return reasons


def render_comparison(
    left: dict, left_bytes: bytes, right: dict, right_bytes: bytes, appearance: str
) -> bytes:
    reasons = _pair_eligibility(left, right)
    document = _start("Saved reference comparison", appearance)
    document.add(
        '<header id="overview"><h1>Saved reference comparison</h1>'
        "<p>Passive comparison of declared model, state and physical action "
        "meanings. No engine replay, search or reference recomputation "
        "runs.</p></header>"
    )
    inspection._facts(
        document,
        [
            ("Left captured SHA-256", hashlib.sha256(left_bytes).hexdigest()),
            ("Right captured SHA-256", hashlib.sha256(right_bytes).hexdigest()),
            ("Comparison eligible", not reasons),
            ("Remaining boundaries", reasons),
            (
                "Producer identities equal",
                _same(left["implementation"], right["implementation"]),
            ),
            ("Operational limits equal", _same(left["limits"], right["limits"])),
        ],
    )
    document.add(
        '<nav aria-label="Comparison sections">'
        '<a href="#comparison">Comparison</a>'
        '<a href="#left-meaning">Left model</a>'
        '<a href="#left-values">Left values</a>'
        '<a href="#right-meaning">Right model</a>'
        '<a href="#right-values">Right values</a></nav>'
        '<section id="comparison"><h2>Exact selected root loss comparison</h2>'
    )
    if reasons:
        document.add(
            "<p>These reports are ineligible for a common quality ranking. "
            "No winner is declared. The exact reasons appear above.</p>"
        )
    else:
        choices = [record["diagnostics"]["recommendation"] for record in (left, right)]
        if any(choice is None for choice in choices):
            document.add(
                "<p>Complete adaptive values share the same state and objective. "
                "One or both inputs have no saved recommendation, so selected "
                "action quality cannot be ranked.</p>"
            )
        else:
            losses = [
                _fraction(choice["value_loss"], "/diagnostics/value_loss")
                for choice in choices
            ]
            description = (
                "The saved choices have equal exact adaptive value loss."
                if losses[0] == losses[1]
                else "The left saved choice has lower exact adaptive value loss."
                if losses[0] < losses[1]
                else "The right saved choice has lower exact adaptive value loss."
            )
            document.add(
                "<p>"
                + description
                + " This applies to the shared state and declared two-round "
                "objective only.</p>"
            )
            inspection._facts(
                document,
                [
                    ("Left choice and loss", choices[0]),
                    ("Right choice and loss", choices[1]),
                ],
            )
    document.add("</section>")
    for side, record in (("left", left), ("right", right)):
        adaptive = record["format"] == FORMAT
        (_meaning if adaptive else legacy._meaning)(document, record, prefix=side + "-")
        (_values if adaptive else legacy._values)(document, record, prefix=side + "-")
        (_choices if adaptive else legacy._choices)(document, record, prefix=side + "-")
        if adaptive:
            _provenance(document, record, prefix=side + "-")
        else:
            document.add(
                f'<section id="{side}-provenance"><h2>Stored source and producer</h2>'
            )
            for name in ("source_report", "implementation", "decision_report"):
                inspection._fragment(
                    document,
                    record[name],
                    "/" + side + "/" + name,
                    "Complete " + side + " " + name.replace("_", " "),
                )
            document.add("</section>")
    return legacy._finish(document)
