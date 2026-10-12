"""Passive admission of the explicit horizon-one root allocation report.

Saved coordinates and arithmetic are checked without invoking the engine,
reconstructing a state, sampling rewards or treating saved claims as execution.
"""
from __future__ import annotations

from typing import Any

from . import episode_record as records

POLICY = "budget_aware_sequential_halving_v1"
FINAL_RULE = "survivor_mean_visits"
TIE_BREAK = "physical_canonical_order"
ALLOCATION_FIELDS = {
    "policy", "mode", "usable_allowance", "selections", "reward_updates",
    "elimination_rounds", "elimination_key_evaluations", "remainder_samples",
    "phases", "winner", "complete",
}
Coordinate = tuple[int | None, int | None]


def _coordinates(value: Any, path: str) -> Coordinate:
    obj = records._object(value, path, {"card_idx", "target_idx"})
    for name, high in (("card_idx", 6), ("target_idx", 7)):
        if obj[name] is not None:
            records.integer(obj[name], path + "/" + name, 0, high)
    if obj["card_idx"] is None and obj["target_idx"] is not None:
        records._error(path, "Pass requires two null indices")
    return obj["card_idx"], obj["target_idx"]


def _ordered(value: Any, path: str, expected: list[Coordinate]) -> None:
    actual = [_coordinates(action, f"{path}/{index}")
              for index, action in enumerate(records._array(value, path, 0, 57))]
    if actual != expected:
        records._error(path, "must retain the complete physical canonical order")


def saved_coordinates(state: dict) -> list[Coordinate]:
    """Check the admitted saved action convention using plain saved fields.

    This is representation admission of the current explicit report version,
    not a reconstruction or an independent numerical/legality certificate.
    """
    player = state["player"]
    result: list[Coordinate] = [(None, None)]
    if player["hp"] <= 0 or not any(row["hp"] > 0 for row in state["enemies"]):
        records._error("/selected_state", "schema 3 requires a nonterminal boundary")
    if player["hp"] > player["max_hp"] or player["pips"] + player["power_pips"] > 7:
        records._error("/selected_state/player", "unsupported saved resource boundary")
    for index, card in enumerate(state["hand"]):
        multiplier = 2 if card["element"] == player["element"] else 1
        if player["pips"] + multiplier * player["power_pips"] < card["pip_cost"]:
            continue
        if card["card_type"] in {"heal", "blade", "shield"} or card["hits_all"]:
            result.append((index, None))
        elif card["card_type"] in {"damage", "trap"}:
            result.extend((index, target) for target, enemy in
                          enumerate(state["enemies"]) if enemy["hp"] > 0)
        else:
            result.append((index, None))
    return result


def _rounds(size: int) -> int:
    count = 0
    while size > 1:
        count += 1
        size = (size + 1) // 2
    return count


def _minimum(size: int) -> int:
    count = 0
    while size > 1:
        count += size
        size = (size + 1) // 2
    return count


def zero_allocation(action_count: int) -> dict:
    """Declare the zero schedule without constructing or running a search."""
    return {
        "policy": POLICY,
        "mode": "uniform_fallback" if _minimum(action_count) else "halving",
        "usable_allowance": 0, "selections": 0, "reward_updates": 0,
        "elimination_rounds": 0, "elimination_key_evaluations": 0,
        "remainder_samples": 0, "phases": [], "winner": None, "complete": True,
    }


def validate_root_allocation(report: dict) -> None:
    """Check the complete saved schedule and its explicit final treatment."""
    actions = saved_coordinates(report["selected_state"])
    order = {action: index for index, action in enumerate(actions)}
    rows = report["legal_actions"]
    if [(row["card_idx"], row["target_idx"]) for row in rows] != actions:
        records._error("/legal_actions",
                       "must retain every saved physical choice in order")
    raw = {action: row for action, row in zip(actions, rows, strict=True)}
    for index, row in enumerate(rows):
        records._number(row["value_sum"], f"/legal_actions/{index}/value_sum",
                        0, row["visits"])
        if row["mean_shaped_reward"] is not None:
            records._number(row["mean_shaped_reward"],
                            f"/legal_actions/{index}/mean_shaped_reward", 0, 1)

    path = "/root_allocation"
    allocation = records._object(report["root_allocation"], path, ALLOCATION_FIELDS)
    records._choice(allocation["policy"], path + "/policy", {POLICY})
    if allocation["complete"] is not True:
        records._error(path + "/complete",
                       "only complete schedules are decision reports")
    allowance = report["configuration"]["max_sims"]
    for name in ("usable_allowance", "selections", "reward_updates"):
        records.integer(allocation[name], path + "/" + name, allowance, allowance)
    for name, high in (("elimination_rounds", 6),
                       ("elimination_key_evaluations", 114),
                       ("remainder_samples", 64)):
        records.integer(allocation[name], path + "/" + name, 0, high)
    work = report["work"]
    if (work["simulations"] != allowance or work["transitions"] != allowance
            or work["unused_transitions"] != 0):
        records._error("/work", "horizon-one complete allocation spends one "
                       "transition per sample")
    expected_stops = (["transition_allowance", "simulation_cap"] if allowance
                      else ["zero_requested_simulations"])
    if work["stop_reasons"] != expected_stops:
        records._error("/work/stop_reasons",
                       "must retain the fixed allocation stopping order")

    fallback = allowance < _minimum(len(actions))
    mode = "uniform_fallback" if fallback else "halving"
    records._choice(allocation["mode"], path + "/mode", {mode})
    phases = records._array(allocation["phases"], path + "/phases", 0, 6)
    counts: dict[Coordinate, int] = dict.fromkeys(actions, 0)
    active = actions[:]
    used = 0
    keys = 0
    survivor: Coordinate | None = None
    if fallback:
        if phases:
            records._error(path + "/phases",
                           "uniform fallback has no elimination phases")
        for index, action in enumerate(actions):
            counts[action] = (allowance // len(actions)
                              + (index < allowance % len(actions)))
        remainder = 0
    else:
        if len(phases) != _rounds(len(actions)):
            records._error(path + "/phases",
                           "must contain every completed elimination phase")
        for index, saved in enumerate(phases):
            p = f"{path}/phases/{index}"
            phase = records._object(saved, p, {
                "active", "quota", "completed_samples", "statistics", "survivors",
            })
            _ordered(phase["active"], p + "/active", active)
            quota = max(1, (allowance - used) // (_rounds(len(active)) * len(active)))
            records.integer(phase["quota"], p + "/quota", quota, quota)
            completed = quota * len(active)
            records.integer(phase["completed_samples"], p + "/completed_samples",
                            completed, completed)
            statistics = records._array(phase["statistics"], p + "/statistics",
                                        len(active), len(active))
            means: dict[Coordinate, float] = {}
            for position, (action, statistic) in enumerate(
                    zip(active, statistics, strict=True)):
                sp = f"{p}/statistics/{position}"
                row = records._object(statistic, sp,
                                      {"action", "visits", "value_sum", "mean"})
                if _coordinates(row["action"], sp + "/action") != action:
                    records._error(sp + "/action",
                                   "must match the active physical position")
                records.integer(row["visits"], sp + "/visits", quota, quota)
                records._number(row["value_sum"], sp + "/value_sum", 0, quota)
                records._number(row["mean"], sp + "/mean", 0, 1)
                if row["mean"] != row["value_sum"] / quota:
                    records._error(sp + "/mean", "must equal its saved phase "
                                   "sum divided by visits")
                means[action] = row["mean"]
                counts[action] += quota
            chosen = sorted(active, key=lambda action: (-means[action], order[action]))[
                :(len(active) + 1) // 2]
            survivors = sorted(chosen, key=order.__getitem__)
            _ordered(phase["survivors"], p + "/survivors", survivors)
            used += completed
            keys += len(active)
            active = survivors
        survivor = active[0]
        remainder = allowance - used
        counts[survivor] += remainder
    if (allocation["elimination_rounds"] != len(phases)
            or allocation["elimination_key_evaluations"] != keys
            or allocation["remainder_samples"] != remainder):
        records._error(path, "elimination and remainder accounting must match "
                       "the complete schedule")
    if any(raw[action]["visits"] != counts[action] for action in actions):
        records._error("/legal_actions", "raw visits must equal phase and "
                       "remainder allocations")
    # Sequential Node sums and separately accumulated phase sums can differ in
    # binary64 grouping. Their counts and individual means, not regrouped sums,
    # are the admission join.
    sampled = [action for action in actions if counts[action]]
    ranking = sorted(sampled, key=lambda action: (
        action != survivor if not fallback else False,
        -raw[action]["mean_shaped_reward"], -raw[action]["visits"], order[action]))
    _ordered(report["ranking"], "/ranking", ranking)
    winner = (_coordinates(allocation["winner"], path + "/winner")
              if allocation["winner"] is not None else None)
    if winner != (ranking[0] if ranking else None):
        records._error(path + "/winner", "must match the explicit final recommendation")
